# Detailed plan: FABPUB partition rotation — the governed recovery for a permanently blocked repository partition (ah#789 Workstream D)

status: draft 2026-09-08 — awaiting maintainer approval; no runtime edits made
owner: Claude Code session `session_01Rv2aKsUWdEKoWfB5PTpD1B`
issue: Consiliency/agent-harness#789 (Workstream D; acceptance item (5) first half)
base: `ef6a9b18a0eb47981ebf07f56e6fc3d6bbe742d8` (origin/main, 2026-09-08 — carries ah#803/#804/#805)
landing tier: `plan` — cross-vendor board under `plans/decision-interim-president-ratification-20260904.md` (Consiliency/agent-harness#773); ledger row on landing
predecessor: `plans/detailed-789-fabpub-pre-admission-compat-20260906.md` (Workstreams A/B/C; D deferred there to this document)

## Task

Restore **governed** FABPUB publication for a repository whose partition is permanently
`epoch_blocked`, without weakening the permanent-ambiguity contract and without the runtime ever
inferring effect-absence from the remote. Concretely: discharge ah#789 acceptance item (5)'s first
half — "a completed recovery can publish the exact intended branch once" — as a general capability,
and give the one partition that is blocked today an executable route back.

## Measured starting state (read-only inspection, 2026-09-08, host `claw`)

Recorded here because the plan's shape depends on it; every value was read, none inferred.

- Authority root `~/.local/state/phase-loop/fabpub/authority-v1`, bootstrap `fabpub-host-bootstrap-20260904`,
  journal `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, pointer `ACTIVE_BOOTSTRAP` (schema
  `ZeroHistoryBootstrapAuthority.v1`).
- **Exactly one blocked partition:** `1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681`
  = `omniagent-plus`. Its `evidence.jsonl` holds two completed effects (`…58033572`, `…0a68fc6a`, both
  `effect_terminal_observed` → omniagent-plus#17) and one blocked effect `…54771bd3`
  (`provider_call_in_flight` → `outcome_ambiguous_blocked`, reference `unsealed-adapter-start-owner`).
  `admissions.jsonl` has rows for epochs 1 and 2 only — **none** for `…54771bd3`, confirming the
  failure was pre-admission. `adapter-start-owner.json` is present with `sealed: false`,
  `transaction_id b72b68ff…`, `committed_head 076f1e5d…`.
- The partition receipt is `LegacyRepositoryPartitionReceipt.v2`, `ambiguous: false`, `zero_source: true`,
  `legacy_epoch_high_water: 0`, `legacy_completed_effect_keys: []`. **The block therefore comes from the
  canonical evidence row** (`evidence.py:86-95`), not from a legacy-carried receipt
  (`live.py:856-865`).
- The other two partitions on this host are clean: `agent-harness` `50fea8e4…` and `EZBidPro`
  `1a3e011c…`, receipts `ambiguous: false`, no blocked records, no `"ambiguous": true` receipt anywhere.
  Host `ai` carries no FABPUB broker state. The Windows host was **not** checked (its scan errored) —
  see Dependencies.
- `publish_committed_branch_idempotency_key` is `sha256(repo \0 branch \0 head_sha)`
  (`convergence/contracts.py:20-22`). Recomputing it from the canonical identity, branch
  `codex/audit-remediation-roadmap` and head `076f1e5d87acba21b87c188e3a70a0f319b79e60` reproduces
  `54771bd3…` exactly — so the blocked effect is the publish that the recorded 2026-09-06 operator
  override performed out of band as Consiliency/omniagent-plus#28.

## Research summary (all anchors read at base `ef6a9b18`)

- **Where a block is consulted.** `verbs.py:533-534` (`_fresh_publish`) plus three sites in
  `admission.py` (`:326`, `:515`, `:576`), wired through `epoch_blocked=lambda: evidence_store.epoch_blocked`
  at `live.py:3435`, `:3504`, `:3633`. A rotation that produces a *new, unblocked store* satisfies all
  four without touching any of them.
- **Why the block cannot be lifted in place.** `evidence.py:229-230` refuses any append that transitions
  out of `outcome_ambiguous_blocked`, on every caller path. This plan does not propose relaxing it.
- **Receipt authentication is byte-exact.** `load_partition_receipt` (`live.py:792-841`) authenticates a
  chain — identity, ARMED journal, sealed inventory digest, partition-map digest — and finally requires
  `path.read_bytes() == expected.file_bytes(...)`. A successor receipt therefore cannot simply be
  written; it must be *produced* by a sealed inventory and an ARMED journal. Rotation needs its own
  ceremony, not a file edit.
- **Unknown schema fails closed, but with the wrong story.** `load_partition_receipt:806-807` raises
  `LegacyCutoverConflict` on an unrecognised `schema`, and `partition_is_ambiguity_blocked:861-865`
  turns any such failure into `True`. So an old runtime meeting a newer receipt refuses — but reports
  "inherited permanent archived ambiguity", which is false and unactionable. ah#803 set the precedent
  for what this should be instead: a typed, named compatibility refusal.
- **`historical_evidence_roots` is a bootstrap-inventory concept**
  (`_validate_historical_evidence_root`, `live.py:2324-2340`: only `admissions.jsonl`,
  `admissions.lock`, `evidence.jsonl`, `evidence.lock` may be present; each JSONL is strict-parsed).
  The live inventory already carries two such rows. It is **sealed and digest-pinned**
  (`_validate_zero_history_inventory`, `live.py:2424-2429`) and pointed at by `ACTIVE_BOOTSTRAP`, so the
  operator note's phrase "retire the blocked partition into `historical_evidence_roots`" is a
  description of intent, not an available operation: the existing inventory cannot be appended to.
- **A second bootstrap over the same authority root is already refused.**
  `probe_zero_history_bootstrap` (`live.py:2394-2409`) rejects any authority root that is not fresh —
  anything other than `bootstrap.lock` and atomic temps of the two targets is "not fresh". The live root
  holds a sealed inventory, a journal, `ACTIVE_BOOTSTRAP` and `search-locks/`, so re-bootstrapping in
  place cannot be used to launder a block. What is **not** yet established is the same attempt against a
  *fresh* authority root pointed at a namespace that already holds a populated partition; that is a
  falsifier this plan requires (Lane D1), not an assumption.
- **Onboarding shape to copy, not call.** `onboard_zero_legacy_repository` (`live.py:2970-3022`) is the
  existing "repository first seen post-ACTIVE" route: serialized under the latch's activation lock,
  exactly one receipt, a real zero-source proof, generation drained/armed/promoted. Rotation is the same
  shape with a different proof: a successor partition is **not** zero-source — a retired predecessor
  store demonstrably exists.

## Design contract

**D1 — Rotation is a ceremony, journaled and crash-idempotent.** Its own `cutover_id`, its own sealed
inventory and journal, states `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, mirroring
`run_legacy_broker_cutover` (`live.py:1834-1967`) and the bootstrap journal. Crash-idempotence is proven
at every state boundary, in the style of
`test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation`
(`test_fabpub_shared_epoch.py:2700`).

**D2 — The successor receipt is a new schema version with a new proof type.**
`LegacyRepositoryPartitionReceipt.v3` adds the rotation proof: predecessor store digests (the retired
`admissions.jsonl` / `evidence.jsonl` bytes), the predecessor receipt digest, and the attestation digest
(D4). `zero_source` MUST be false for a rotated partition — claiming zero-source with a retired
predecessor on disk would be a false proof. The successor's `ambiguous` MUST be false: carrying the block
forward via `receipt.ambiguous=True` would re-block the new partition through
`partition_is_ambiguity_blocked` and defeat the entire ceremony.

**D3 — The carry is an adjudication, key-granular, not a blanket poison.** The successor receipt carries
`adjudicated_effect_dispositions`: effect key → `{disposition, attestation_digest}`, in the shape of the
existing `legacy_completed_effect_keys`. Exactly two dispositions:

- `observed_landed` — the successor treats the key as a completed terminal: a publish request for it is
  answered as a duplicate, with **no** adapter call and no new provider effect.
- `attested_not_landed` — the successor permits **exactly one** governed publish for that key, after
  which normal idempotency applies.

Every key that carried an `outcome_ambiguous_blocked` record in the predecessor MUST appear with one of
the two dispositions; a rotation that leaves an ambiguous key undisposed is refused. This is what
discharges item (5): the `attested_not_landed` branch is the "publish the exact intended branch once"
capability, and `observed_landed` is the branch omniagent-plus needs.

**D4 — The attestation is human-authored and recorded; the runtime never reads the remote.** A rotation
requires an attestation document naming, per ambiguous key: the observed world-state, the evidence a
human looked at (PR/branch URL), who attested, and when. Its digest is pinned into the successor receipt.
The ceremony MUST NOT call `git ls-remote` or any network probe — "no branch on origin" and "`ls-remote`
timed out" remain the same observation to this runtime (ah#789 acceptance item 3). The distinction this
plan relies on is *who* observes: an accountable operator, recorded, not an inference by the runtime.

**D5 — Version skew, split into what can and cannot be fixed.** Three distinct obligations, because
conflating them produces an untestable requirement:

1. *Forward (implementable).* The v3-aware reader refuses an **unknown or future** receipt schema with a
   typed, named compatibility error carrying the runtime location — the ah#803
   `AdmissionStoreIncompatible` precedent — instead of routing it through
   `partition_is_ambiguity_blocked` and reporting "inherited permanent archived ambiguity". This fixes
   the class going forward.
2. *Backward compatibility (load-bearing, currently unanchored).* The v3 reader MUST keep authenticating
   **v2** receipts byte-exactly. `agent-harness` `50fea8e4…` and `EZBidPro` `1a3e011c…` are live v2
   partitions on this host; a rotation feature that breaks a clean partition is a worse outcome than the
   block it is fixing.
3. *Retroactive (impossible, mitigated operationally).* A runtime installed **before** v3 cannot be made
   to report the typed error: its `load_partition_receipt` raises `LegacyCutoverConflict` on the unknown
   schema (`live.py:806-807`) and `partition_is_ambiguity_blocked` (`:861-865`) converts that to `True`,
   so the operator sees the misleading permanent-block message. That behaviour is frozen in shipped code
   and this plan does not pretend otherwise. Mitigation is operational: re-pin every installed
   `phase-loop-runtime` to a v3-aware build before Lane D5 — the same re-pin the predecessor plan carried,
   and a stale `uv tool` install from a worktree was ah#789's root cause.

**D6 — Fencing.** The ceremony runs under the bootstrap seal locks and the writer-generation latch: the
predecessor drains, the successor arms and promotes a fresh generation. After ACTIVE, a writer still
holding the retired store path fails closed.

**D7 — The retired store is preserved, never deleted.** It moves to a historical classification whose
file set matches `_validate_historical_evidence_root`'s allowlist, and stays byte-identical: the
`outcome_ambiguous_blocked` record for `b72b68ff…` is evidence, and this plan does not rewrite it.

## Lanes

Lanes D2 and D3 are disjoint by file from Lane D4 and may run in parallel once Lane D1's RED anchors exist.

### Lane D1 — falsifiers first (tests_only)

`phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py` (new). RED at this base, per the repo's
RED-first idiom (`_fabpub_tdd_guard.py` gating, `fabpub_capability_active()`, `FABPUB_SKIP_REASON`), and
registered in the frozen node-id inventory the same way the ah#789 lanes were.

Anchors:
1. A blocked partition, rotated with `observed_landed` for its ambiguous key, publishes NOTHING for that
   key (no adapter call, no new evidence row) and answers the request as a duplicate.
2. The same rotation with `attested_not_landed` permits exactly one adapter call for that key, and a
   second attempt is refused by ordinary idempotency.
3. A rotation that leaves an ambiguous key undisposed is refused before anything durable is written.
4. The retired store's `admissions.jsonl` and `evidence.jsonl` are byte-identical before and after.
5. Crash injection at each journal boundary leaves the ceremony resumable and never leaves two routable
   receipts for one identity.
6. A v3-aware reader meeting an **unknown/future** receipt schema raises the typed compatibility refusal
   naming the schema and the runtime location, not `partition_is_ambiguity_blocked`'s ambiguity message.
7. A v3-aware reader still authenticates an untouched **v2** receipt byte-exactly, and a clean v2
   partition publishes through the governed path unchanged (regression anchor for `agent-harness` and
   `EZBidPro`).
8. **The laundering falsifier:** a fresh authority root pointed at a namespace that already holds a
   populated partition must refuse to bootstrap. If it does not, closing that hole joins this plan's
   scope and the finding is recorded in the PR body.

### Lane D2 — receipt schema and the rotation ceremony (production)

`convergence/broker/live.py`: `LegacyRepositoryPartitionReceipt` → v3 with the rotation proof and
`adjudicated_effect_dispositions`; a `rotate_blocked_partition(...)` entry point in the shape of
`onboard_zero_legacy_repository`; the rotation inventory/journal/seal-lock helpers; the typed pre-v3
refusal (D5).

### Lane D3 — dispositions honoured on the publish path (production)

`convergence/broker/verbs.py` `_fresh_publish` and its replay path: an `observed_landed` key resolves as a
completed terminal before any owner is written; an `attested_not_landed` key proceeds exactly once. No
change to the four `epoch_blocked` consult sites and none to `evidence.py:229-230`.

### Lane D4 — operator surface and docs

A `phase-loop fabpub rotate-partition` command that takes the attestation document and drives the
ceremony; `docs/fabpub-pre-admission-ambiguity.md` gains the rotation section (replacing "deferred");
CHANGELOG entry.

### Lane D5 — execute the omniagent-plus rotation (operational, not a PR)

After D1–D4 land: attest `…54771bd3` as `observed_landed` citing Consiliency/omniagent-plus#28 and the
2026-09-06 override comment, rotate `1da3e343…`, and demonstrate one governed publish for omniagent-plus.
Requires a separate maintainer authorisation; nothing here executes it.

## Documentation impact

- `docs/fabpub-pre-admission-ambiguity.md` — modify — replace "Partition rotation (deferred)" with the
  landed ceremony, and update the carried-item paragraph once item (5) is discharged.
- `CHANGELOG.md` `## [Unreleased]` — add — one entry per landed lane.
- `plans/manifest.json` — add — `type=detailed` entry for this plan.
- `specs/phase-plans-v10.md` — none (LEGIBLE-owned; no roadmap goal changes).
- `plans/decision-interim-president-ratification-20260904.md` — ledger row per production_code/plan landing.

## Dependencies & order

1. Maintainer approval of this document → plan-tier board → land (ledger row).
2. **Fable-seat availability is a landing risk, named up front.** The native fable sub-agent override
   produced no output for three consecutive ah#805 rounds on 2026-09-08 (a default-model sub-agent ran the
   same smoke test in seconds); Consiliency/agent-harness#806 tracks the missing policy. This plan lands
   either on four seats or on a recorded deviation of the ah#805 shape — never silently on three.
3. Lane D1 (RED anchors) before D2/D3.
4. D2 before D3 (D3 consumes the receipt field); D4 after D3.
5. D5 after all lanes land, with its own authorisation, and **only after every installed
   `phase-loop-runtime` on a host that can write FABPUB state is re-pinned to a v3-aware build**
   (`uv tool install --force "git+https://github.com/Consiliency/agent-harness@<main sha>#subdirectory=phase-loop-runtime"`,
   never from a working checkout) — see D5 part 3.
6. Unchecked precondition: the Windows host has not been scanned for blocked partitions. Before D5,
   scan every host that can write FABPUB state, so a rotation is not performed while a second blocked
   partition is unknown.

## Verification

- CI-faithful suite (source mode, `PYTHONPATH=$PWD/src:$PWD/tests`):
  `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests /mnt/workspace/venvs/ah-779-ci/bin/python -m pytest
  -p no:cacheprovider -o addopts="" -q tests/test_fabpub_partition_rotation_789d.py
  tests/test_fabpub_shared_epoch.py tests/test_fabpub_zero_history_bootstrap.py
  tests/test_fabpub_recovery_controls_789.py` — all green; frozen corpus counts unchanged
  (`test_fabpub_guard_nodeid_inventories_are_disjoint_and_counted`).
- Every falsifier in Lane D1 RUN and its observed failure text recorded in the PR body — never "should
  fail".
- Named mutants, each RUN, in the ah#805 style: (m1) drop the undisposed-key check → anchor 3 passes;
  (m2) carry the block as `receipt.ambiguous=True` → the successor is blocked, anchors 1–2 fail;
  (m3) let `observed_landed` reach the adapter → anchor 1's adapter counter is 1;
  (m4) let `attested_not_landed` publish twice → anchor 2's second attempt succeeds;
  (m5) route an unknown schema through the ambiguity path instead of the typed refusal → anchor 6 gets the
  misleading permanent-block message; (m6) tighten the reader to accept only v3 → anchor 7's clean v2
  partition stops authenticating.
- Read-only host re-inspection after D5: the retired store's two JSONL files digest-match the values
  pinned in the successor receipt.

## Acceptance criteria

- [ ] A rotation of a blocked partition whose ambiguous key is attested `observed_landed` yields a
      successor partition that publishes a fresh, unrelated branch through the governed path, and answers
      the attested key as a duplicate with zero adapter calls (falsified by m3).
- [ ] The same rotation attested `attested_not_landed` permits exactly one governed publish of the exact
      intended branch and refuses the second by ordinary idempotency (falsified by m4). This is ah#789
      acceptance item (5)'s first half, discharged as a capability rather than restated.
- [ ] A rotation leaving any predecessor `outcome_ambiguous_blocked` key undisposed is refused before any
      durable write (falsified by m1).
- [ ] The successor receipt authenticates through `load_partition_receipt` byte-exactly, carries
      `zero_source: false` and `ambiguous: false`, and pins the predecessor digests plus the attestation
      digest (falsified by m2).
- [ ] A v3-aware reader raises a typed compatibility refusal naming the schema and the runtime location
      for an unknown/future receipt schema (falsified by m5), and still authenticates an untouched v2
      receipt byte-exactly so a clean v2 partition publishes unchanged (falsified by m6). The pre-v3
      install's misleading message is documented as unfixable retroactively, with the re-pin as its
      mitigation — not claimed as fixed.
- [ ] The predecessor store is byte-identical after rotation, including the
      `outcome_ambiguous_blocked` record for `b72b68ff…`; `evidence.py:229-230` is untouched.
- [ ] Crash injection at every rotation journal boundary is idempotent and never leaves two routable
      receipts for one canonical identity.
- [ ] The runtime performs no network or `git ls-remote` call anywhere in the ceremony, proven by the
      recording sentinel idiom from `test_fabpub_recovery_controls_789.py`.
- [ ] The laundering question is answered in the PR body with a RUN result: whether a fresh authority root
      can bootstrap over a populated namespace, and — if it can — the guard that closes it.

## Execution Policy

- execute: effort=high, reason=a new authority-ceremony and a receipt schema version on the fencing path;
  every anchor is a fail-closed guarantee and the failure mode is silent unblocking.
