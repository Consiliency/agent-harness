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

No release tag contains the ceremony (D2, Consiliency/agent-harness#816) yet,
and the package version string is still `0.7.14`, so `--version` cannot tell a
v3-aware install from a pre-v3 one (claw's git-pinned install and the `v0.7.14`
release both report `0.7.14`) — use the probe. Pin to the exact `main`
commit that carries D4:

```bash
uv tool install --force \
  "git+https://github.com/Consiliency/agent-harness@c98573ebd45452451ce719406f5b28379284b4c9#subdirectory=phase-loop-runtime"
python3 phase-loop-runtime/scripts/fabpub_v3_probe.py   # against that interpreter; expect exit 0
```

Known caveat (Consiliency/agent-harness#819): every install at or after
`b09b1a47` (claw's current `463b90c3` included; the `v0.7.14` release predates it) prints `built-in closeout validator fab_gate is not importable; gate
NOT registered` on the CLI's first import. It is a circular-import regression
in the closeout validator registry, unrelated to the ceremony; the rotation
verb is unaffected, but note it in the record rather than treating it as a
failure of the pin.

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
  namespace, a `generations/` store, or an authority's `partition-rotations/`
  ceremony directory. (The verb independently refuses to *read* an attestation
  from the ceremony directory — `cli.py::_load_rotation_attestation`; this
  refuses to *write* one there, so a mistyped `--out` cannot land on a sealed
  inventory.)
- an `outcome_ambiguous_blocked` row exists for the key.

What the builder **derives**, and the reviewer must re-check:

- `ambiguity_digest` is the sha256 of the **latest** `outcome_ambiguous_blocked`
  row for the key, raw line text, no trailing newline.
- `owner_nonce` / `transaction_id` are emitted **only** when
  `adapter-start-owner.json` names this effect key (either spelling —
  `effect_key` or `idempotency_key`), copied verbatim, and **omitted** when it
  does not: the adjudicator refuses both a missing value when the owner names
  the key and a present one when it does not (`live.py:4321-4326`). The builder
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
its first journal row (cutover-id grammar, repository snapshot, attestation
location and readability, container receipt shape and non-ambiguity, bootstrap
claim binding to this authority, active bootstrap, no foreign staging debris,
no other rotation in progress, own-journal state, predecessor adjudication,
inventory derivation, the sealed inventory on a pre-flip resume, and the
writer-generation latch) by calling the same functions, then reports the drain
facts the verb will meet *after* its first row: the armed marker, held lease
files, and live pre-FABPUB writers. Verdicts:

- `ready` — every validation check passes and no lease file is held.
- `ready_but_drain_will_block` — validation passes but lease files are held;
  the verb would write `DRAINING` and then refuse (§5, run 1). Fix the leases
  (§6) before executing.
- `already_completed` — the active generation is already this cutover id's
  successor. The verb's post-flip completion path would finish idempotently;
  the preflight mirrors that path, so it adjudicates the **predecessor**
  generation and requires the sealed inventory to derive from *this*
  attestation (see §7).
- `would_refuse` — a validation check refuses; the report names it. Nothing
  durable would have been written.

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

**No check can prove a lease is orphaned.** `acquire` writes a JSON file and
returns; it takes no `flock` and records no pid, so absence of a holder is
unobservable (that is exactly Consiliency/agent-harness#820). The procedure
below therefore does not *detect* orphans — it **removes the possibility of a
holder** by stopping every candidate process, and only then treats the
remaining files as debris.

1. **Stop the candidates and their descendants, and suppress new starts.**
   Quiesce whatever would start a broker on this host (the phase-loop driver
   session, any scheduled run-train, any agent loop that publishes) for the
   duration of the ceremony. Then, for each candidate pid, stop the whole
   process group (`kill -TERM -<pgid>`, never `pkill -f`), and confirm the
   descendants are gone (`ps --ppid <pid>`) — a forked child can hold the
   broker after its parent exits.
2. **Enumerate candidates three ways**, because no single scan is complete:
   - `fabpub_rotation_preflight.py` — an empty `live_pre_fabpub_writers` list.
     This matches only an exact `run-train` argv element behind a `phase*`
     launcher (`_iter_live_run_train_processes`), so it is necessary, not
     sufficient.
   - `ps -eo pid,pgid,lstart,args | grep -E 'phase[-_]loop|run-train'` — catches
     differently-launched runtimes, but not a broker embedded in a process
     started as `python3 <script>.py`.
   - the kernel's own view, which needs no argv guess:
     `ls -l /proc/[0-9]*/cwd 2>/dev/null | grep <worktree>` and
     `ls -l /proc/[0-9]*/fd 2>/dev/null | grep phase-loop-fabpub-broker-v1`.
3. **Re-run the enumeration after the stop** and require all three empty.
   Only then is the lease-mtime argument admissible as corroboration: each
   lease predates every process still running (the four omniagent-plus leases
   are dated 2026-09-04 10:47/11:08 and 2026-09-05 20:55/21:01; the
   2026-09-05 incident's runner is gone).

Then, with the go recorded on the issue and new starts still suppressed,
remove the lease files (and only those):
`rm <namespace>/generation-leases/<nonce>.json`. Do not touch
`writer-generation.json`, `writer-generation.lock`, or `cutover-armed`. Re-run
the preflight; expect the string `ready`. Keep new starts suppressed through
§7 — a broker that starts between the removal and the flip takes a fresh
lease and the drain blocks again.

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
this check on both resume paths, so run it before every resume.

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

## 9. Residuals carried out of the 2026-09-09 preparation

- Consiliency/agent-harness#819 — `fab_gate` circular import on `git+main`
  installs (cosmetic for this verb; real for closeout).
- Consiliency/agent-harness#820 — leases carry no liveness; orphan detection is
  manual (§6).
- `leno` unscanned (offline); never held FABPUB state.
- No release tag carries D2/D4; the re-pin is by commit SHA until one does.
