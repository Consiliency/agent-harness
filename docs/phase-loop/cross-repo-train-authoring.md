# Cross-repo release train: authoring guide

This guide covers how to author a train roadmap for `phase-loop run-train`.
For the technical protocol spec (ledger shape, merge-SHA gate, invariants) see
`_contract_docs/phase-loop/protocol.md` ("Cross-Repo Release Train").

## What a train roadmap does

A train roadmap declares a set of per-repo phase-loop plans and their
dependency edges. The coordinator (`train_runner.run_train`) reads this file,
derives a topological execution order, and drives:

1. **Preflight** — every repo's plan is validated before any PR opens.
2. **Drafts-open (P3)** — per-repo `run_loop` calls open draft PRs in topo order.
3. **Governed merge (P4, `--governed` only)** — a train-level review panel
   reviews the entire multi-repo diff, then merges sequentially. Each downstream
   re-verifies against the upstream **MERGED SHA** (not the draft SHA) before
   its own merge.

## File format

```markdown
# Release Train: <name>

## Nodes

### Node: <repo> / <plan-path>

**Depends on:** (none)
**Channel:** (none)

### Node: <downstream-repo> / <downstream-plan>

**Depends on:** <repo> / <plan-path>
**Channel:** submodule path=<path-to-submodule>
```

One `### Node:` block per repo/plan pair. Node identifiers
(`<repo> / <plan-path>`) must be unique within the train.

### Optional node attributes

| Attribute | Values | Default | Meaning |
|-----------|--------|---------|---------|
| `**Mode:**` | `execute` \| `prebuilt` | `execute` | `execute` runs the per-repo `run_loop` to build the node's phase, then publishes what it produced. `prebuilt` lands an **already-committed, independently-verified branch** WITHOUT re-executing the phase (no executor dispatch) — see below. |
| `**Workspace:**` | absolute path | `<workspace-root>/<repo>` | Per-node checkout location, for nodes that live on arbitrary paths/volumes. Overridden by the `--workspace <repo>=<path>` CLI flag. |

An unknown `**Mode:**` value is rejected at parse time with a coded, node-named
error (`(T-G) node '<id>' declares unknown mode ...`) — zero PRs open.

### Prebuilt nodes

A `**Mode:** prebuilt` node publishes a branch that already carries the
committed work. The coordinator:

1. **Preflights** the workspace as CLEAN (no uncommitted changes) AND strictly
   **ahead of `origin/main`** (it carries the committed work). A clean-but-not-ahead
   prebuilt node is a preflight error — nothing to publish (zero PRs open).
2. **Skips `run_loop`** entirely — no executor dispatch, no upstream injection
   (injection would dirty the clean tree and force a re-commit).
3. Derives the PR's owned paths from the **committed diff** vs base
   (`git diff --name-only origin/main...HEAD`).
4. **Publishes via the credential broker** — the same broker-mediated,
   exact-head-verified path used by execute nodes. A prebuilt node run under a
   broker-authoritative coordinator pushes the existing branch (by name, no
   `--force`) and opens a **draft PR** with **no new commit**. Without a broker
   the publish fails closed (`broker_required`); a prebuilt node never does a
   direct push.

Prebuilt nodes stop at `drafts_open` like execute nodes. A prebuilt root with no
upstream edge supports governed review and merge, pinned to its admitted head.
A prebuilt node with any upstream edge, including `order-only`, is refused under
`--governed`: downstream re-verification still requires phase-loop state. Keep
that node at `drafts_open`; a prebuilt-aware downstream verifier is separate work.

Example prebuilt train (each node's branch already carries verified commits):

```markdown
# Release Train: land-prebuilt-work

## Nodes

### Node: platform-lib / specs/feature-x.md

**Depends on:** (none)
**Channel:** (none)
**Mode:** prebuilt

### Node: app-service / specs/feature-x-consumer.md

**Depends on:** platform-lib / specs/feature-x.md
**Channel:** submodule path=vendor/platform-lib
**Mode:** prebuilt
**Workspace:** /mnt/workspace/checkouts/app-service
```

## Review material and zero-model preview

For each new governed review, supply `--review-material material.json`. The
coordinator derives the full PR patch from the unique merge base of the live
base tip and the ledger-admitted head. A `CHANGELOG.md` node label does not limit
that scope. Source comes from isolated readers of Git objects, never dirty
working files, external diff drivers, textconv, hooks, or implicit fetches.

Once every node is admitted, prepare and inspect the packet before reviewing:

```sh
phase-loop run-train --train train.md --governed --review-only \
  --review-material material.json --preview-review /absolute/empty/preview --json
phase-loop run-train --train train.md --governed --review-only \
  --review-material material.json
phase-loop run-train --train train.md --governed
```

Add `--monitoring-policy heartbeat_only` to the review commands to run the train
review the way `advisor-board --monitoring-policy heartbeat_only` does. It seats the
frozen four-vendor default board with no model deadline, and a vendor that is down
fails its own seat rather than being replaced. There is no native host seat, so it
cannot combine with `--emit-native-request` or `--native-leg`. Unsupported routes and
an unqualified Gemini/agy route are refused before any ledger or broker effect. With
`--preview-review`, the receipt reports `review_monitoring_policy` and the
`review_board` seats. The default, `bounded`, composes the board at review time.

Use `--ledger-dir DIR` consistently for a nondefault coordinator ledger. Preview
reads existing admission state and GitHub metadata before any broker, lease,
recovery, admission, or model call. It writes `packet.md`, `packet.json`, optional
operator-only `removals.json`, and `receipt.json` into a fresh/empty directory
outside node checkouts, the ledger, and `.phase-loop`. Output components may not
be symlinks. `ready=true` means material preparation, not source approval.

The version-1 JSON manifest has exactly `schema_version: 1` and `nodes`, an
object keyed by every exact train node ID. Each node requires:

- `head_sha`: full admitted Git OID.
- `acceptance`: nonempty records `{id, text, provenance: {path, sha256}}`.
- `verification`: nonempty records, either `{id, kind: "github_check_run",
  check_run_id, expected_name?, expected_app_slug?}` or
  `{id, kind: "attested_command", head_sha, argv, exit_code, result,
  attested_by, observed_at, evidence: {path, sha256}}`.
- Optional `context`: Git paths at the admitted head; missing context is an
  explicit review dissent. Optional `generated_removals`: declarations below.

Evidence paths are relative to the manifest directory, cannot contain `..`,
and every component is opened without following symlinks. Evidence must be a
regular file with its declared lowercase SHA-256. Bytes are captured once and
included in the packet. IDs are unique within each record list; unknown fields
and stale heads hold. `observed_at` is RFC3339. A passed command requires integer
exit code 0; failed requires a nonzero integer; skipped/unknown require null.
Local records are **operator-supplied attestations**, not authenticated runtime
executions. GitHub check-run identity, repository, head, app and raw status are
bound; optional expected name/app pins are reported when absent. Failed, skipped,
unavailable and unknown outcomes cannot be promoted to passed.

An optional removal declaration is `{path, base_tree_oid, rationale,
attestation: {path, sha256}}`. Its attestation file is JSON containing
`attested_by`, `observed_at`, `base_tip_sha`, `merge_base_sha`, `head_sha`, `path`,
`base_tree_oid`, and nonempty `disposal_scope`. All identities must match.
The subtree must exist unchanged at both merge base and live base tip and be
entirely absent at head. Root groups, top-level `.github`, CODEOWNERS-containing
subtrees, overlaps, and new outside exact-blob copies (including empty blobs)
are refused. This proves mechanical whole-tree deletion, **not generatedness**
or absence of semantic copies. The board sees an explicit disposal assertion,
counts, bounded histograms, full inventory/diff digests and attestation text;
deleted bodies and individual rows are represented by the certificate and are
not claimed model-read. The complete inventory remains operator-only. Moving
the base requires refreshed base-bound attestations and another review, even
if that subtree is unchanged. Other binary/submodule changes hold.

Direct patch text escapes literal backslashes, CR and transport-disallowed
Unicode reversibly, preserving LF/TAB separators. JSON sections require outer
escape decoding, JSON parsing, then decoding nested `content.text` to recover
original evidence/source bytes. Unicode escapes use four hex digits after `\u`
or eight after `\U` for supplementary characters; the latter requires the packet
escape grammar to be decoded before JSON parsing, because standard JSON string
decoders do not accept `\U`. `raw_sha256` hashes those original bytes;
`escaped_sha256` hashes intermediate escaped text before JSON/outer encoding.
Preview `presentation_sha256` hashes the final rendered section. Forbidden broker frame replicas
hold. The 1 MiB parser limit is not transport readiness: the **complete rendered
prompt** must fit 512 KiB with its real brief/framing and a conservative sandbox
path bound. Oversized input requires separately reviewed scope decomposition;
the runtime never truncates or silently spends extra rounds.

Approval records optionally carry `review_packet_sha256`. Cached approval needs
that digest, intact immutable packet storage, current live identities and the
current usable-reviewer floor. Legacy count-only approvals re-review. Explicit
new material is compared; omitting it retains stored evidence snapshots, not
newly refreshed checks. Partial merge resume retains original reviewed sections
for already merged nodes after checking full admission identity (node, branch,
PR, head and FAB run) and live merge outcomes.
Without valid historical material it holds as `historical_packet_unavailable`.
Observed base/head drift before approval or each merge holds remaining work;
this is not an atomic base pin or a promise against concurrent GitHub changes.

Ordinary governed merge execution may use the existing trusted FAB readmission
opt-in. It first classifies every pending node and freezes the full prospective
packet, requiring all evidence to bind the proposed head and all Git objects to
exist locally. Invalid material anywhere holds before recovery or delta review.
Existing broker readmission then establishes durable authority; only matching
fresh ledger bindings can promote those identical frozen bytes for train review.
The coordinator never advances a head after reviewing its packet. Current
readmission eligibility is checked again immediately before recovery. While FAB
promotion is active, recovery and every later approval/merge gate recheck actual repository revocation evidence;
absent or unreadable evidence namespaces hold while FAB promotion is active.
Promotion-off retains the existing flag semantics and still requires admitted,
current heads. Read-only review and native emission never readmit or recover;
native fills requiring a new admission hold, and request emission returns even
when approval is cached. Preview never reads broker evidence.

After native request emission, fill the request and re-run the original command
with the printed continuation flags, replacing the emission flag. Keep the same
train, workspace overrides and ledger directory, and retain the original
`--review-material` file when supplied. Emission does not record approval, so a
fresh fill cannot retrieve its material through the approved-packet cache.

Packet identity, material and revocation checkpoints—including finalization,
storage, and checks immediately before review and approval—report `review_halted`
before this packet's recovery/readmission begins and `merge_halted` after it begins.
The recovery/readmission loop uses the same effect boundary. Only its per-node
failure handler appends a blocked row, and only after that node's helper entry;
later packet holds retain the latest durable binding without appending a row.
Normal panel rejections and native-fill refusals remain `review_halted`.
Merge-loop refusals remain `merge_halted`. Specific reasons (for example
`admission_identity_drift`) survive, and earlier merges remain recorded. Missing
historical node bindings hold explicitly. Packet readback detects missing/corrupt
files; malformed stored shapes and excessive JSON nesting produce a hold receipt.
Power-loss durability and recovery are tracked separately in agent-harness#977.

The configured coordinator supervise tier is advisory provenance only. Preview
readiness proves Git coverage and harness transport fit; it does not prove that
a provider consumed all material. Reported truncation is not a usable approval,
and this workflow grants no extra supplier review round.

## Channel types

A channel tells the coordinator how to update the downstream workspace's
upstream reference before re-verify at merge time.

| Channel | Syntax | Use when |
|---------|--------|----------|
| `submodule` | `submodule path=<path>` | Downstream uses a git submodule at `<path>` pointing to the upstream repo. |
| `pin file` | `pin file=<file> key=<yaml-key>` | Downstream reads the upstream SHA from a YAML pinfile at `<file>` under key `<key>`. |
| `order-only` | `order-only` | Downstream must merge **after** the upstream (freeze/merge order) but does **not** consume its artifact. No SHA is injected or re-resolved; the edge enforces ordering only. |

Declare `**Channel:** (none)` for root nodes (no upstream dependency).
Declare `**Depends on:** (none)` for root nodes.

For a **dependency** edge you must declare a channel: `pin`/`submodule` if the
downstream consumes the upstream, or `order-only` for a pure merge-order (freeze)
dependency. A bare `**Channel:** (none)` on a dependency edge is rejected (it is
ambiguous — likely a forgotten channel).

## Expand/contract recommendation

The coordinator updates the downstream's upstream pin to the **MERGED SHA**
of the upstream before re-verifying. However, the downstream PR itself was
opened with the **draft-time pin** — the SHA of the upstream PR's head at the
time the draft was created. This means the merged downstream PR carries the
draft-time pin, not the merge-commit SHA.

**To keep sequential merges safe**, use expand/contract upstream contracts:

1. **Expand** — the upstream change is additive and backward-compatible. The
   downstream continues to work with either the old or new interface. Merge
   the upstream first (the coordinator does this automatically in topo order).
2. **Contract** — the downstream adopts the new interface. Because the upstream
   is already merged (and the downstream re-verifies against its merged SHA),
   this merge is safe.

Avoid breaking upstream changes that require the downstream and upstream to
merge atomically — the train cannot guarantee zero-gap ordering.

## Example: submodule train

```markdown
# Release Train: add-feature-x

## Nodes

### Node: platform-lib / specs/feature-x.md

**Depends on:** (none)
**Channel:** (none)

### Node: app-service / specs/feature-x-consumer.md

**Depends on:** platform-lib / specs/feature-x.md
**Channel:** submodule path=vendor/platform-lib
```

The coordinator opens the `platform-lib` PR first, then the `app-service` PR.
At merge time, `app-service` re-verifies after its `vendor/platform-lib`
submodule pointer is updated to the merged `platform-lib` SHA.

## Example: pinfile train

```markdown
# Release Train: bump-runtime

## Nodes

### Node: runtime-core / specs/runtime-v2.md

**Depends on:** (none)
**Channel:** (none)

### Node: worker-fleet / specs/runtime-bump.md

**Depends on:** runtime-core / specs/runtime-v2.md
**Channel:** pin file=.config/pins.yaml key=runtime_sha
```

## Running the train

```sh
# P3 only: open draft PRs (no merge)
phase-loop run-train --train train.md

# P3+P4: open drafts, review panel, sequential merge
phase-loop run-train --train train.md --governed

# Resume after a blocked node (re-run the same command):
phase-loop run-train --train train.md --governed

# Point a node at an arbitrary checkout path (repeatable; overrides
# **Workspace:** and --workspace-root):
phase-loop run-train --train train.md \
    --workspace app-service=/mnt/workspace/checkouts/app-service
```

The coordinator is crash-resumable: nodes already merged are skipped; blocked
nodes are retried. Use the same `--train` file on every run.

## Topo order

Dependencies are declared; order is computed. The coordinator calls
`roadmap.topo_order()` — you do not need to list nodes in dependency order.
Cycles are rejected at parse time.

## Safety invariants (structural)

- **Zero PRs on preflight failure** — all repos must pass preflight before any PR opens.
- **No merge before train approval** — `--governed` gates the full diff through a review panel; rejection is non-human terminal.
- **False-green killer** — `set_upstream_ref` is called with the MERGED SHA and re-verify runs *after* before each downstream merge.
- **Train state off `.phase-loop/`** — the ledger is never written inside any repo's `.phase-loop/` directory.
- **Autonomous boundary** — without `--governed`, the coordinator stops at `drafts_open`; cross-repo merges are never auto-merged.

## Converged coordinator behavior

The phase-loop command recovers the coordinator event log before every
dispatch, resume, publish, review, merge, release, or package action and
compares it with exact Git, GitHub, provider, and registry authority. A
missing probe, unsupported/mixed version, stale attempt or fence, invalid
verification artifact digest, stale approval, or ambiguous provider result is
a fail-closed typed blocker.

Each admitted mutation is bound to an immutable attempt, epoch, fence token,
approval digest, expected-version predicate, authority scope, and idempotency
key. Provider credentials stay within the broker boundary. Parallel execution
requires different repositories, complete disjoint owned paths, frozen shared
interfaces, and a recorded isolation decision; merges and release publication
remain serial. Following a merge, refresh each affected downstream to the
exact merge SHA, rerun its bound verification, then request a fresh broker
admission for republish/review.

For the full protocol spec see
`phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md`.
