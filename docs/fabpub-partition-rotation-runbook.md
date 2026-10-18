# FABPUB partition rotation — operator runbook

Operator procedure for retiring a permanently blocked FABPUB repository
partition with `phase-loop fabpub-rotate-partition`. The ceremony itself, its
guarantees, and the attestation document are specified in
`docs/fabpub-pre-admission-ambiguity.md` ("Partition rotation"); this runbook is
the *operational* wrapper around that verb: the fleet gate that must hold before
it runs, the read-only preflight that predicts its verdict, a rehearsal technique
that exercises the real verb over byte copies, and the post-flip steps.

It was written for Lane D5 of Consiliency/agent-harness#789 — rotating the
omniagent-plus partition blocked in the 2026-09-05 incident — and the worked
values below are that partition's. Every step before "Execute" is read-only
against live state; the state-changing steps are marked and each needs the
maintainer's explicit go.

## 0. Vocabulary and paths

| Term | Value for the omniagent-plus rotation |
|---|---|
| worktree | `/home/viperjuice/code/omniagent-plus` |
| broker namespace | `<worktree>/.git/phase-loop-fabpub-broker-v1/` |
| container (generation 0) | `<namespace>/repositories/1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681/` |
| authority root | `~/.local/state/phase-loop/fabpub/authority-v1/` |
| ceremony directory | `<authority>/partition-rotations/<identity>/` |
| blocked effect key | `publish_committed_branch\0` + `54771bd3b9168ba4b01d0f9f9c89016634929b698421f5970d4fd4182c3a70c3` |
| cutover id | `fabpub-rotation-omniagent-plus-gen1-20260909` |
| attestation (draft) | `~/.local/state/phase-loop/fabpub/operator/attestations/1da3e3…7681-gen0.json` |

The repository identity embeds the *absolute* git common dir, and the ceremony
inventories and receipts embed absolute paths; nothing below may be exercised
against a relocated copy of the store (see §5 for how to rehearse at the real
paths without touching the real bytes).

The three helper scripts live in `phase-loop-runtime/scripts/` and run from a
checkout with `PYTHONPATH=phase-loop-runtime/src` (or against an installed
runtime that is v3-aware — §2):

- `fabpub_v3_probe.py` — does *this* interpreter's `phase_loop_runtime` know
  `LegacyRepositoryPartitionReceipt.v3`? exit 0 yes / 2 no / 3 not importable.
- `fabpub_rotation_attestation.py` — builds the attestation from the live
  container (read-only; the only write is `--out`).
- `fabpub_rotation_preflight.py` — runs the verb's zero-write validation checks
  (including its two resume paths) and the drain facts, and prints the verdict
  the verb would reach.

## 1. Preconditions (plan Lane D5, Dependencies item 3)

- (a) The runtime that will run the verb, and every runtime that will *read* the
  partition afterwards, is v3-aware. A pre-v3 runtime does not follow
  `generations/ACTIVE`: it resolves to the container and refuses on generation
  0's own ambiguity block rather than misreading the successor. That is a hard
  stop for that host, not a silent corruption — but a pre-v3 process holding a
  fresh lease can still append a non-publish terminal into the retired
  generation, which the next replay refuses fail-closed. Pin, do not rely on
  the refusal.
- (b) The attestation names every blocked key with a reviewed disposition and
  the evidence that established it.
- (c) No writer of the predecessor generation is alive when the ceremony
  reaches `DRAINING`; the ceremony counts writer-generation lease files, and
  refuses (keeping its journal) while any remain.

## 2. Fleet host gate (read-only)

Scan every host that can hold a `phase-loop-runtime` and a checkout of the
repository. Per host: which runtime is installed (`phase-loop --version`, and
the probe), whether any FABPUB state exists (`~/.local/state/phase-loop/fabpub/`,
any `.git/phase-loop-fabpub-broker-v1/`), and whether any `run-train` /
governed-publish process is alive.

Result of the 2026-09-09 scan:

| Host | Runtime | FABPUB state | Live writers | Gate |
|---|---|---|---|---|
| claw (this host) | `uv tool` `phase-loop-runtime` 0.7.14, git pin `463b90c3` (12 commits before D4; predates D2) — **not v3-aware** (probe exit 2) | authority + omniagent-plus namespace; **4 orphaned writer-generation leases** | 0 (`LegacyWriterQuiescence` scan) | re-pin (§2.1) + lease removal (§6) |
| ai | reports 0.7.14; pin origin not inspected — probe before use | none | 0 | re-pin before it reads the partition |
| macmini | reports 0.7.14; pin origin not inspected — probe before use | none | 0 | re-pin before it reads the partition |
| win | no `phase-loop` on PATH, no state dir | none | 0 | clean |
| leno (Windows, Tailscale) | **unscanned — offline** | unknown | unknown | must scan before go, or accept as residual (it has never held FABPUB state) |

### 2.1 Runtime re-pin

The ceremony (D2, Consiliency/agent-harness#816) and D4 ship in every release
from `v0.7.15`. The rotation retry in §8a also needs agent-harness#1296, first
released in `v0.7.25`. Install a released runtime at or above `0.7.25`, then
confirm it with the probe, because `--version` alone does not prove what a
git-pinned install carries:

```bash
uv tool install --force phase-loop-runtime   # or pin: phase-loop-runtime==<version >= 0.7.25>
python3 phase-loop-runtime/scripts/fabpub_v3_probe.py   # against that interpreter; expect exit 0
```

The protections described in §8a for an `attested_not_landed` decision
(agent-harness#1313, agent-harness#1577, agent-harness#1591) are newer than
`v0.7.26`; see §8a.

## 3. Attestation (read-only build, reviewed by hand)

```bash
python3 phase-loop-runtime/scripts/fabpub_rotation_attestation.py \
  --container "<worktree>/.git/phase-loop-fabpub-broker-v1/repositories/<identity>" \
  --out ~/.local/state/phase-loop/fabpub/operator/attestations/<identity>-gen0.json \
  --attested-by "<operator>" \
  --effect-key-suffix 54771bd3b9168ba4b01d0f9f9c89016634929b698421f5970d4fd4182c3a70c3 \
  --observed-head 076f1e5d87acba21b87c188e3a70a0f319b79e60 \
  --evidence-url https://github.com/Consiliency/omniagent-plus/pull/28 \
  --override-record https://github.com/Consiliency/agent-harness/issues/789#issuecomment-5560313217
```

What the builder **enforces** (exit 2, nothing written):

- `--container` carries a `LegacyRepositoryPartitionReceipt.v2` — the
  generation-0 container shape. Pointed at a rotated store it refuses rather
  than digest the wrong generation's bytes.
- `--out` is an operator path: not under a `phase-loop-fabpub-broker-v1/`
  namespace (which is where every generational store lives) and not under an
  authority's `partition-rotations/` ceremony directory. (The verb independently refuses to *read* an attestation
  from the ceremony directory — `cli.py::_load_rotation_attestation`; this
  refuses to *write* one there, so a mistyped `--out` cannot land on a sealed
  inventory.)
- an `outcome_ambiguous_blocked` row exists for the key.

What the builder **reports** without refusing (agent-harness#1591): every row of
the container's `post-ambiguity-observations.jsonl` for the key — a provider
outcome the broker saw after the key was already blocked — and whether it binds
this blocked row. It prints a `WARNING` when `--observed-head` or
`--evidence-url` differs from a recorded effect, and when the file is unreadable
(the ceremony then refuses `attested_not_landed` for every key). A human
publication handoff with `required_disposition: observed_landed` carries a
pre-filled builder argv (`attestation_builder_command`, generation-0 containers
only) with these inputs; fill in `--out` and `--attested-by`.

What the builder **derives**, and the reviewer must re-check:

- `ambiguity_digest` is the sha256 of the **latest** `outcome_ambiguous_blocked`
  row for the key, raw line text, no trailing newline.
- `owner_nonce` / `transaction_id` are emitted **only** when
  `adapter-start-owner.json` names this effect key (either spelling —
  `effect_key` or `idempotency_key`), copied verbatim, and **omitted** when it
  does not: the adjudicator refuses both a missing value when the owner names
  the key and a present one when it does not (in `live.py`, the `owner_nonce` /
  `transaction_id` check after `_rotation_owner_identity` during rotation adjudication). The builder
  prints which half it emitted.
- a digested file that is absent digests as `sha256(b"")`, matching
  `_snapshot_predecessor`.
- `observed_head` is **not** checked against the owner record's
  `committed_head` by the builder or the ceremony — the builder only prints
  `==`/`!=`. Equality is the *reviewer's* criterion: the disposition is
  `observed_landed` only because the branch is observed on the remote at that
  head *and* the publication was reviewed (omniagent-plus#28).

Draft produced 2026-09-09 (marked "DRAFT … pending operator go" in
`attested_by`; the operator re-runs the builder with their own `--attested-by`,
which changes both digests below):

| | |
|---|---|
| file sha256 | `fefc63755981abf08039275589ebbfbf32b085e1c26895d14933a6d5fd92dccc` |
| canonical digest (`attestation_sha256` in the result/receipt) | `f74febd3afb3e47da7d41ad70ad178c05655ae1848d9fb2b3e77a2854034c53a` |
| `ambiguity_digest` | `1a74835debb81aefd7351bca7fcbde0e76fd4b30debba03fb45e2bd7b110e568` |

The two digests differ because the ceremony digests the *canonical* JSON of the
document, not the file bytes; record both.

## 4. Preflight (read-only)

```bash
cd phase-loop-runtime && PYTHONPATH=$PWD/src python3 scripts/fabpub_rotation_preflight.py \
  --worktree <worktree> --attestation <attestation> \
  --cutover-id fabpub-rotation-omniagent-plus-gen1-20260909 --json
```

The script runs, in the verb's own order, every check the verb performs before
it can succeed (cutover-id grammar, repository snapshot, attestation
location and readability, container receipt shape and non-ambiguity, bootstrap
claim binding to this authority, active bootstrap, no foreign staging debris,
no other rotation in progress, own-journal state, predecessor adjudication,
no `attested_not_landed` entry for a key with a recorded post-ambiguity effect or
while that side file is unreadable (`no_attested_not_landed_over_observed_effect`,
agent-harness#1591; skipped, as by the verb, on a resume whose own journal already
holds `INVENTORY_SEALED`, where the successor's re-admission refuses instead),
inventory derivation, the sealed inventory on a pre-flip
resume, and the writer-generation latch) by calling the same functions, then
reports the drain
facts the verb will meet *after* its first row: the armed marker, held lease
files, and live pre-FABPUB writers. Verdicts:

- `ready` — every validation check passes, no lease file is held, and no live
  pre-FABPUB writer is present.
- `ready_but_drain_will_block` — validation passes but a lease file is held or
  a live pre-FABPUB writer is present; the verb would write `DRAINING` and then
  refuse (§5, run 1). Clear the cause (§6) before executing.
- `already_completed` — the active generation is already this cutover id's
  successor. The verb's post-flip completion path would finish idempotently;
  the preflight mirrors that path, so it adjudicates the **predecessor**
  generation, requires the sealed inventory to derive from *this* attestation
  (see §7), requires the journal to have reached `ARMED`, and applies the
  completion path's **own** latch predicate: the latch must exist and its state
  must be `DRAINING` or `ACTIVE`. Both of those gates sit *after* the
  completion path appends its `ACTIVE` journal row, so a refusal there has a
  durable write behind it and must never read as a go. The `ARMED` marker is
  deliberately **not** required: the finish calls `mark_armed()` before
  `activate()` and so recreates it, and requiring it would refuse a rotation
  the verb completes.
- `would_refuse` — a validation check refuses; the report names it. On a first
  execution nothing durable would have been written. On the completion path
  the verb's own latch gates sit after its `ACTIVE` journal append, so a
  refusal there is one the verb reaches *with* that row already written —
  which is precisely why it must not read as a go.

Exit status is 0 for `ready` and `already_completed` (the verb would succeed)
and 1 otherwise. **The first-execution go-gate is the string `ready`**, not
merely exit 0.

2026-09-09 result for omniagent-plus: all 15 validation checks pass;
`ready_but_drain_will_block` on the 4 orphaned leases; 0 live writers.

## 5. Rehearsal over byte copies (read-only against live state)

The ceremony only makes sense at the real absolute paths, so a rehearsal
bind-mounts *copies* of the namespace and the authority over the real paths
inside an unprivileged user+mount namespace and runs the real verb there.
Nothing outside the namespace is written; sha256-sweep the live trees before and
after to prove it.

```bash
OUT=<scratch>/rehearsal; NS=<worktree>/.git/phase-loop-fabpub-broker-v1
AUTH=~/.local/state/phase-loop/fabpub/authority-v1
cp -a "$NS" "$OUT/ns"; cp -a "$AUTH" "$OUT/auth"
# optional: rm -f "$OUT"/ns/generation-leases/*.json   (rehearse the post-§6 state)
find "$NS" "$AUTH" -type f | sort | xargs sha256sum > "$OUT/live-before.sha"
unshare -Urm --propagation private bash -c "
  mount --bind '$OUT/ns' '$NS' && mount --bind '$OUT/auth' '$AUTH' &&
  cd phase-loop-runtime && PYTHONPATH=\$PWD/src python3 -m phase_loop_runtime.cli \
    fabpub-rotate-partition --worktree <worktree> --attestation <attestation> \
    --authority-root '$AUTH' --cutover-id <cutover-id> --json"
find "$NS" "$AUTH" -type f | sort | xargs sha256sum > "$OUT/live-after.sha"
diff "$OUT/live-before.sha" "$OUT/live-after.sha" && echo LIVE UNTOUCHED
```

`--authority-root` is passed **explicitly**, and `$AUTH` must be the root the
verb would resolve on its own: `default_fabpub_authority_root()` honours
`PHASE_LOOP_FABPUB_AUTHORITY_ROOT` and then `XDG_STATE_HOME`, so a value set in
the operator's shell would send every ceremony write to a live root the
`find "$NS" "$AUTH"` sweep does not cover. Resolve it first
(`python3 -c 'from phase_loop_runtime.convergence.broker.live import
default_fabpub_authority_root as d; print(d())'`), copy *that*, and mount and
pass *that*. Neither variable was set on claw on 2026-09-09, so the run below
used the documented default.

2026-09-09 rehearsal of the omniagent-plus rotation, two runs:

- **run 1 (leases as found)** — exit 1:
  `partition_rotation_refused: predecessor writers did not drain:
  legacy_writer_after_fabpub_activation: DRAINING did not reach zero before
  INVENTORY_SEALED: 4 held generation lease(s)`. The copy's ceremony directory
  holds one `DRAINING` journal row for the cutover id and nothing else; generation
  0 unchanged. This is exactly the verdict the preflight predicted.
- **run 2 (orphaned leases removed in the copy)** — exit 0,
  `PartitionRotationResult.v1`: `generation 1`, `state ACTIVE`,
  `receipt_schema LegacyRepositoryPartitionReceipt.v3`,
  `legacy_epoch_high_water 2`, `adjudicated_effect_keys` = the one blocked key,
  `restart_required true`. `generations/ACTIVE` names `1`; the successor's
  completed effects carry the three legacy keys; generation 0's four store files
  are byte-identical to before.
- Live trees byte-identical before and after both runs.

## 6. Stop writers and clear orphaned leases — STATE CHANGE, needs go

A writer-generation lease (`<namespace>/generation-leases/<nonce>.json`) is
released only by `_RoutingBrokerService.close()`; a broker process that exits
without closing leaves the file behind, and the lease carries no pid or
liveness token (Consiliency/agent-harness#820). The ceremony counts files, so an
orphan blocks the drain exactly like a live writer.

**No check can prove a lease is orphaned, and the scans below are not
jointly complete either.** `acquire` writes a JSON file and returns: it takes no
`flock`, records no pid, and need not keep a descriptor open. A broker embedded
in a process whose argv names neither `phase-loop` nor `run-train`, whose cwd is
outside the worktree, and which holds no open descriptor under the namespace,
escapes **all three** scans at once; a detached child reparents to init and
disappears from `ps --ppid <parent>`. That is Consiliency/agent-harness#820.

So the scans are **corroboration, never authorisation**. What authorises the
deletion is a **shutdown boundary**: an instant after which no process that
could hold a lease is running.

**The boundary is a maintenance reboot of the host, with every phase-loop /
agent launcher disabled before it comes back** so nothing can take a lease
between the boundary and the ceremony. There is no cheaper sound alternative,
and in particular a "stop everything older than the newest lease" rule is not
one: a broker can take a lease and then fork a detached child that outlives it,
and that child *starts after the lease it inherits the use of*, so a start-time
cutoff never selects it, it survives termination of its parent's process group,
and it is invisible to `ps --ppid`. Selecting by argv fails for the same reason
the scans below do.

If the maintainer chooses to proceed at go-time without a reboot, that is a
**deviation, not an option this runbook offers**: it must be recorded on
Consiliency/agent-harness#789 as an explicit acceptance that a surviving
lease-holder cannot be ruled out, together with the reasoning for accepting it.
The paragraph at the end of this section bounds what that residual can and
cannot do.

With the boundary established and new starts still suppressed, corroborate —
these confirm the boundary held, they do not establish it:

1. `fabpub_rotation_preflight.py` reports an empty `live_pre_fabpub_writers`
   list. It matches only an exact `run-train` argv element behind a `phase*`
   launcher (`_iter_live_run_train_processes`) — necessary, not sufficient.
2. `ps -eo pid,pgid,lstart,args | grep -E 'phase[-_]loop|run-train'` — catches
   differently-launched runtimes, not an embedded broker.
3. The kernel's own view, which needs no argv guess:
   `ls -l /proc/[0-9]*/cwd 2>/dev/null | grep <worktree>` and
   `ls -l /proc/[0-9]*/fd 2>/dev/null | grep phase-loop-fabpub-broker-v1`.

Require all three empty, and require every lease file to predate the boundary
(the four omniagent-plus leases are dated 2026-09-04 10:47/11:08 and 2026-09-05
20:55/21:01; the 2026-09-05 incident's runner is gone).

Then, with the go recorded on the issue and new starts still suppressed, remove
the lease files (and only those):
`rm <namespace>/generation-leases/<nonce>.json`. Do not touch
`writer-generation.json`, `writer-generation.lock`, or `cutover-armed`. Re-run
the preflight; expect the string `ready`. Keep new starts suppressed through §7
— a broker that starts between the removal and the flip takes a fresh lease and
the drain blocks again.

**What the residual buys, if a holder survived anyway.** Deleting its lease
destroys the drain's evidence, which is why the boundary and not the scans is
the authorisation. It does not, however, let that holder corrupt the retired
generation silently: its writes through the broker API are fenced by the
`DRAINING` latch and by the successor's generation nonce after the flip, and any
change to the predecessor's digested bytes between the attestation and the drain
refuses the ceremony fail-closed (`the predecessor store changed between
attestation and drain; re-attest over the current bytes`). The failure mode is a
refused ceremony or a fenced writer, not a silent divergence. A routing client
from `build_routing_broker_client()` that a surviving holder built before the
flip refuses every later request with `WriterGenerationBlocked` (`this broker
client is bound to retired partition generation …`) before it reads or writes
either generation's store. It never rebinds itself, so restart that process
(agent-harness#1315). The refusal's type is `RoutingClientGenerationRetired`, and
the human route answers it with next step `rebuild_broker_client_and_retry`, not
`repair_fabpub_authority`.

## 7. Execute — STATE CHANGE, needs go

On the pinned runtime, from any cwd:

```bash
phase-loop fabpub-rotate-partition \
  --worktree <worktree> --attestation <attestation> \
  --cutover-id fabpub-rotation-omniagent-plus-gen1-20260909 --json
```

Expected: exit 0 and the `PartitionRotationResult.v1` document of §5 run 2
(with the operator's own `attestation_sha256`). Record the full JSON on the
issue.

If it refuses after durable progress (a writer reappeared, a failure in the
post-flip finish): the journal for this cutover id is kept, a *different*
cutover id is refused as "in progress", and the fix is to remove the cause and
re-run the **same** command with the **same** `--cutover-id` **and the same
attestation file** — the verb resumes; re-running after completion is the
idempotent no-op.

The attestation identity matters from `INVENTORY_SEALED` onward: the resume
requires the sealed inventory to derive from the attestation the re-run
supplies, and *any* change to the document — a different `--attested-by`, a
fresh `attested_at` from re-running the builder — changes its canonical digest
and is refused with `rotation … sealed a different attestation; resume with
the sealed one`. Keep the exact file; do not rebuild it. The preflight mirrors
this check on both resume paths, so run it before every resume. On a resume whose
own journal already holds `INVENTORY_SEALED`, both the verb and the preflight skip
the post-ambiguity observation check; the successor's re-admission refuses an
observed effect instead (agent-harness#1633). If the successor then refuses a key
with `publication_recovery_required` naming an observed effect, follow §8a: escalate
to the maintainer and do not re-publish (agent-harness#1640).

A re-run never repairs its inputs (a damaged authentication-chain link or
writer latch after the flip is refused by every re-run until the bytes are
restored from outside).

## 8. After the flip

1. **Restart every broker process** that resolved the repository before the
   flip (`restart_required`): its stores are bound to the retired generation and
   its next write is refused until it re-resolves. On claw there are none alive
   (§2); on other hosts, none has ever resolved this repository.
2. Verify: `repository_snapshot(<worktree>).store_root` ends in
   `generations/1`; `load_partition_receipt` returns the v3 receipt; the
   pre-dispatch replay answers the `…54771bd3` key as a duplicate with no owner
   read (Lane D3 behaviour).
3. **Governed publish demo** (the second half of ah#789 acceptance item 5): run
   one governed publish through the rotated partition and record that it
   admits, dispatches, and seals with `generation 1`.
4. Close out on Consiliency/agent-harness#789 with the result JSON, the
   attestation digests, and the per-host re-pin evidence.

## 8a. Recovering a failed publication of the current head (`attested_not_landed`)

**Scope corrections are not same-context recovery.** The human adapter hashes
`owned_paths` into its checkpoint context. Supply the complete branch-to-base
scope, including already-committed companion changes, rather than only dirty
paths. Its early scope precheck refuses omitted committed paths before creating
a commit or acquiring publication authority; the broker independently validates
the final branch. Correct the scope and retry an early precheck refusal.

If an older adapter already committed and received a broker scope rejection,
changing `owned_paths` selects a different context. The procedure below does not
authorize rebinding that transaction. Normal retry may report `nothing_staged`,
and prebuilt preparation intentionally rejects a commit carrying a FABPUB intent
trailer. Preserve the original commit and evidence; do not remove the trailer,
make an empty commit, or edit checkpoints to escape the recorded terminal.
Recovery with changed scope uses the explicit `PublishScopeCorrection.v1`
operation below, not a same-context rotation claim.

Use this when a human or governed publication failed with an ambiguous
provider outcome (for example `outcome_ambiguous_blocked` / `push-unconfirmed`,
or an adapter exception), the publish transaction for the **current** head is
past `COMMITTED_HEAD_RESOLVED` (normally `TERMINAL_SEALED`), and the operator
has reviewed the case and established that the push did not land.
Before any rotation, the human route (`publish_human_invoked_from_worktree`)
answers such a publication, and every retry of it, with next step
`adjudicate_publication_by_partition_rotation`: the result's `terminal_state` is
`outcome_ambiguous_blocked`, and the handoff carries the `rotate_command` for the
worktree and what the rotation requires (agent-harness#1312). Retrying before the
rotation replays the same block with no provider call. If the review instead
establishes that the push landed, the disposition is `observed_landed` (§3) and the
retry after the rotation replays it as published.
Runtime 0.7.24 and earlier refuse this retry after the rotation
(`broker admission precondition denied`) and leave a new unsealed owner in the
successor generation. Re-pin to a release that contains agent-harness#1296
before rotating.

**If the handoff says `required_disposition: observed_landed`, do not attest
`attested_not_landed`.** The broker enters the provider only after, within one
`admissions.lock` acquisition, the on-disk owner equalled its attempt's (nonce
included) and was unsealed and the key's row was `provider_call_in_flight`
(agent-harness#1577). A promotion landing at any point from that lock's release
through the provider call (the `ADAPTER_STARTED` projection, request finalization,
lease acquisition, the call itself) still makes one provider call, reported with
`provider_call_made: true`. When that call returns a definite outcome the broker keeps
it in `post-ambiguity-observations.jsonl` and every attempt and retry is answered with
reason `effect_observed_after_ambiguity` (or `no_effect_observed_after_ambiguity`)
and `observed_after_ambiguity` (agent-harness#1591). For an effect, the handoff keeps
`next_step: adjudicate_publication_by_partition_rotation` and adds
`required_disposition: observed_landed`, `forbidden_disposition:
attested_not_landed` and `attestation_inputs` (observed head, evidence URL, effect-key
suffix, owner nonce, transaction id); build the attestation from them (§3) and the
retry after the rotation replays the PR as published. The ceremony, the preflight and
the re-admission refuse `attested_not_landed` for such a key, and for every key while
the side file is unreadable. If an older ceremony accepted one anyway, the retry is
refused with `publication_recovery_required` naming the observed effect: escalate to
the maintainer and do not re-publish. A no-effect observation is listed as
`supporting_evidence` and leaves the judgement to you.

**If `post-ambiguity-observations.jsonl` is unreadable** (the ceremony, the preflight or
the retry names it; typically a torn final line from a crash mid-append), do this:

1. Never truncate, edit or delete the file. It is the only record of what the provider
   reported, and repairing it would turn the fail-closed refusal into a guess.
2. Read the torn tail with the partition's `admissions.lock` held (for example
   `flock <store>/admissions.lock tail -c 4096 <store>/post-ambiguity-observations.jsonl`),
   so no writer appends while you read.
3. If the partial line names the blocked key (its `idempotency_key`, or the effect-key
   suffix), treat it as an effect. Confirm the pull request at the provider and rotate
   `observed_landed` with that head and the provider-side URL (§3); never
   `attested_not_landed`.
   A row is written with its fields in sorted order (`ambiguity_digest`, `branch`,
   `evidence_reference`, `head_sha`, `idempotency_key`, `observed_state`, then the
   owner bindings), so a torn line can show the pull request URL and head without the
   key, or name the key and stop before `observed_state` (agent-harness#1640):
   - **The URL or head without the key.** If the branch and head are this
     publication's, treat the line as naming it and continue as above.
   - **The key without the outcome.** The line does not say whether the provider
     reported an effect or no effect. Treat it as a possible effect: if the head is on
     the remote branch or a pull request exists for it, rotate `observed_landed` as
     above. If the provider shows neither, go to step 4; a missing `observed_state` is
     not a no-effect observation.
4. Otherwise escalate to the maintainer. Do not rotate `attested_not_landed` while the
   file is unreadable: the ceremony refuses it for every key, and so does the retry.

The same applies to a well-formed row this runtime cannot read, such as one carrying a
field from a newer runtime: read it, act on what it names, and escalate if it is unclear.

**Before attesting `attested_not_landed`, check which runtimes write the partition.**
The liveness lock, the guard and the observation protect a partition only once every
runtime that writes it, and every runtime that runs its ceremony, is upgraded. These
protections landed on `main` after `v0.7.26`; a `v0.7.26` or older runtime counts as
not upgraded. An
older writer records no observation, a crash between the provider's return and the
side-file write loses it, and an older re-admitter can still publish an effect an
older ceremony attested not landed. Until every runtime is upgraded, base the
disposition on provider-side evidence, such as no pull request and no branch for the
head at the provider. Absence of local evidence is not enough, and provider-side
absence remains the operator's judgement, not proof. A blocked result with
`provider_call_made: false`
means that call never entered the provider. A retry that replays an earlier block
also reports `false`, so it says nothing about the earlier attempt's effect. A failure between the owner section and
the provider call (`record_intent`, a checkpoint projection, a refused lease) leaves
the owner in place, and the next attempt promotes it. That case is
`attested_not_landed` by construction. See `docs/fabpub-pre-admission-ambiguity.md`,
"Provider entry and failures around it".
For a generation refusal in that window (`WriterGenerationBlocked`, raised as
`ProviderEntryGenerationRefused`) or the guard's own "no evidence row" refusal
(`ProviderEntryRefused`), the human route answers with next step
`retry_once_before_partition_rotation`. Any other `PermissionError` there, such as
EACCES or an incompatible store, keeps `repair_fabpub_authority`. Until one retry
promotes the owner, the row is still `provider_call_in_flight`, and the rotation
refuses with "intents without a terminal". Retry once. The retry returns the
rotation handoff for this key. Keep the first result as the attestation's evidence
that the provider was never entered. The ambiguous row alone cannot show that
(agent-harness#1594 asks 1 and 5).
The same next step can follow a refusal **after** provider entry, with
`provider_call_made: true` (agent-harness#1628). The adapter raised, or it returned
and its terminal record was refused (`execute_returned: true`, agent-harness#1684), and
the generation fence (a `DRAINING` latch during a rotation ceremony, or a revoked
lease) refused the `outcome_ambiguous_blocked` record, so no terminal was written: the
row is still `provider_call_in_flight` and the owner unsealed. The outcome is not
recorded, so the "by construction" reasoning above does not apply. Retry once after
any rotation ceremony in progress has finished or rolled back (the latch is `ACTIVE`
again), then follow the handoff the retry returns. Keep the first result: when the
adapter returned, its `pr_url` and `head_sha` are the provider's returned pull
request, which the retry does not repeat. In the attestation, dispose the key
`observed_landed` with that URL and head; without one, `observed_landed` if the head
is on the remote branch or a pull request exists for it, otherwise
`attested_not_landed` is your judgement, and remote absence is not proof.

1. Leave the worktree, branch, commit, plan file and verification artifact
   exactly as they were. Do not make an empty commit, switch branch, force
   push, rebuild the proof, or edit checkpoint or broker files.
2. Build the attestation (§3) with `disposition: attested_not_landed`, no
   `observed_head`, and the owner's `owner_nonce` and `transaction_id` copied
   verbatim. The `transaction_id` must equal the sealed checkpoint's; a
   disposition that binds no transaction id authorizes nothing. A later missing
   remote ref, or a successful `git push --dry-run`, is not proof that the
   historical attempt had no effect. The attestation is the operator's judgement
   and should cite the review in `evidence_url`.
3. Preflight (§4) until the verdict is the string `ready`, then execute (§7).
4. Restart any broker process (§8 step 1).
5. Retry the **same** publication call — same worktree, owned paths, plan,
   verification artifact, `prebuilt` flag and PR body. Expected: one provider call for the exact sealed commit,
   `status: published`, and a new
   `publish-transactions/<node>/<transaction_id>.recovery.<generation>.json`
   beside the checkpoint, which the SDK closeout then seals. A second retry is answered from evidence
   with no provider call.

**Retrying after a later rotation.** The disposition stays valid across later
rotations for other keys (agent-harness#1310). The retry walks the authenticated
receipt chain back to the disposing rotation, and records both generations in
the recovery record (`disposing_generation`, `readmitting_generation`,
`intervening_rotations`). These three fields appear only when a rotation
intervened; a same-generation record keeps the agent-harness#1296 shape
(agent-harness#1576). It is refused, with nothing written, once any
generation since the disposing rotation holds evidence or an adapter-start
owner for the key, or a later receipt carries or re-adjudicates it. A
disposition authorizes one re-admission. Retrying promptly is still best, and a
retry is refused if any receipt in the chain fails to authenticate.

**After an ambiguous recovery attempt**, generation N+1 is blocked again. Do not
attest `attested_not_landed` a second time without new evidence that this attempt
did not land either. Two ambiguous pushes are not evidence of no effect.

Do not retry on a runtime without agent-harness#1296 after the rotation: it
refuses at admission and leaves an unsealed owner that blocks the new
generation.

**Mixed runtime versions (agent-harness#1576).** Within one generation, a retry
on an agent-harness#1296 runtime and a retry on a current runtime write the same
recovery record, so either may follow a crash of the other after the record and
before the owner. An agent-harness#1296 runtime has no live-owner check
(agent-harness#1313), so do not retry on one while another attempt may still be
running: a retry that races a live attempt can leave the key ambiguous even after
a real provider call (agent-harness#1629 ask 2). A runtime built from `main` after agent-harness#1550 and before this
fix (never released) wrote the three fields even with no rotation. A current runtime
accepts that record, but the agent-harness#1550 runtime refuses a current
runtime's record. Retry such a refusal on a current runtime. Only a current runtime
recovers after an intervening rotation. An older runtime refuses that retry with
`publication_recovery_required` before it records anything.
If a retry fails with `publication_transaction_conflicted` and the handoff names
`conflicting_recovery_record`, that file disagrees with what this runtime
authorizes. The file records an authorization, written before the owner. It does
not prove that an admission happened. Compare it with the refusal detail and with
that generation's evidence and adapter-start owner for the key before changing
anything, and escalate to the maintainer. If the retry is refused with `publication_recovery_required`, the
message names what did not bind and the next step for that case (no disposition, a disposition already used or
superseded in a later generation, no transaction id, a different transaction, or a chain that does not authenticate). Nothing was written;
fix the input and retry.

## 8b. Correct a sealed ownership-scope refusal

`publish_human_invoked_from_worktree` accepts
`scope_correction_from=(original_checkpoint_root, original_node_id)` with the
corrected `owned_paths`. Keep the same worktree, branch, commit, detailed plan,
verification artifact, base, draft intent and PR body; leave `prebuilt=False`.
The corrected scope must strictly include the original scope and cover the real
branch-to-base diff. The SDK creates a successor checkpoint with the original
commit bytes and trailer, without creating a commit or changing a branch ref.

The broker authenticates the active generation's exact original
`no_effect_terminal_proven` row with an `owned-scope-exceeded:` reason and sealed
owner. It reserves one immutable `PublishScopeCorrectionReceipt.v1` under the
admission lock and admits a separate successor effect key. Competing corrections
with different scopes refuse. An identical retry reuses the reservation and
replays a completed successor without another provider call. The original
checkpoint and canonical effect row remain unchanged; ordinary retries of the
original request still replay its original result.

Missing or changed predecessor/proof, a generic provider rejection, ambiguity,
an observed effect, an unsealed owner or a retired generation does not authorize
this operation. An ambiguous successor reports `review_scope_correction_outcome`;
preserve its evidence and review the actual outcome. This version cannot
authenticate the original no-effect row after partition rotation, so it does not
offer rotate-then-retry recovery. A missing active predecessor returns
`inspect_scope_correction_predecessor`; recovering it across generations needs
an additional supported receipt-chain operation. There is no second
scope-correction successor. A reservation alone is not a
publication. Use matching SDK and broker support; older supported SDK entrypoints
do not accept the new keyword. Do not edit receipts or use generic prebuilt mode
to imitate it.

## 9. Residuals carried out of the 2026-09-09 preparation

- Consiliency/agent-harness#820 — leases carry no liveness; orphan detection is
  manual (§6).
- `leno` unscanned (offline); never held FABPUB state.
- D2/D4 ship in `v0.7.15` and later; the §8a retry needs `v0.7.25` or later (§2.1).
