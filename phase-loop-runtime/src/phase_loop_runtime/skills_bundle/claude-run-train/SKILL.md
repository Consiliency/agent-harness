---
name: claude-run-train
description: "Claude Code entry point for the cross-repo release-train coordinator. Use when the user wants to run, resume, or inspect a multi-repo train roadmap: draft PRs across all nodes in topo order, gather train-level review, then merge sequentially with downstream re-verification."
---

# Harness Run Train

Thin bridge for the `phase-loop run-train` coordinator. All preflight,
draft-PR sequencing, train-level review, sequential merge, and downstream
re-verify logic lives in the runtime; this skill is the human entry point only.
Do NOT re-implement or contradict runtime guarantees here.

## Core Rules

Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.

- Use the repo-local CLI: `phase-loop run-train --train <train-roadmap-file>`.
- Pass `--governed` to enable the merge phase (train-level review + sequential
  merge + downstream re-verify). Omitting `--governed` stops at `drafts_open`.
- Pass `--governed --review-only` to run the train-level review of the ADMITTED heads
  and stop BEFORE any merge (`review_approved`): approval is recorded on the ledger and a
  later `--governed` run reuses approval only for identical packet bytes and current
  identities/reviewer-floor evidence. Review-only publishes nothing: a node
  without an admitted open PR, or a prebuilt workspace whose HEAD moved past its admitted
  head, is refused (`review_only_requires_admitted_prs`) before any board or publication; an admitted
  head that no longer matches the live PR head halts as `review_halted` / `stale_head`.
  `--review-only` without `--governed` is a usage error.
- Under Claude Code the train review's <harness> seat is filled NATIVELY by this session (REVIEWTRUTH
  early slice, EC-REVIEWTRUTH-14): run `--governed --review-only --emit-native-request` first (it
  stages the bundle and `request.json` under `<ledger-dir>/native-fill/<request_id>/` and spends
  nothing), spawn a native sub-agent with `instructions.md` as its brief over `artifact.md`, write its
  review (verdict on the LAST non-empty line) to `review.md` beside them, then re-run with
  `--governed --review-only --native-leg claude=<that dir>`. A moved train refuses the fill as
  `native_fill_stale_request` before any seat is spent; re-emit. The fill counts only once bound.
- The train-level review runs through the broker-authorized review board (the same
  authorization sequence as `advisor-board`); a held review names each reviewer leg's
  refusal, never only `no_usable_review`.
- Do NOT invoke `phase-loop run` on the train roadmap file — that is the
  per-repo loop and will not orchestrate a multi-repo train.
- Do NOT merge, force-push, or close PRs outside the coordinator; the runtime
  enforces the partial-merge and false-green guards.
- Prebuilt nodes (`**Mode:** prebuilt`): a prebuilt node with NO upstream edge lands
  under `--governed` like any other node (train review, then merge pinned to its
  admitted head). A prebuilt node with ANY upstream edge, order-only included, is
  refused at preflight under `--governed` (its re-verify needs phase-loop state a
  prebuilt node does not carry); run without `--governed` and it stops at
  `drafts_open`. Do not merge such a PR by hand; that support is a tracked follow-up.
- Refreshing an open prebuilt PR: when the node's workspace HEAD advances past the
  broker-admitted head (a fast-forward), re-running the train republishes the node
  through fresh broker admission and a non-force push to the same branch; the open PR
  is reconciled at the new head and the ledger gains a new `pr_open` record (the old
  one is kept). The coordinator refuses BEFORE any admission when the live PR head
  differs from the admitted head (`remote_drift`) or when HEAD does not descend from
  the admitted head (`candidate_diverged`). A PR closed out of band is lifecycle
  drift: the node republishes as a new PR by the existing resume rule.
- Inspect `phase-loop train-status --train <file>` to check the ledger without
  modifying state.

## Inputs

- Train roadmap path: a Markdown file with `## Nodes` listing
  `### Node: <repo> / <plan>` entries with `**Depends on:**` and
  `**Channel:**` fields.
- Optional `--governed` flag: activates train-level review → sequential merge →
  downstream re-verify.
- Optional `--ledger-dir DIR`: coordinator ledger directory for crash-resume.
- `--review-material FILE`: version-1 manifest keyed by exact node IDs, with admitted
  heads, acceptance provenance and head-bound verification evidence.
- `--preview-review DIR`: with `--governed --review-only`, prepare immutable packet
  files and a ready/hold receipt in a fresh empty directory without models or writes
  to broker, admission, lease or ledger state.

Trusted FAB readmission in ordinary governed execution freezes all proposed-head
material before recovery or delta review, then requires matching durable broker
admission before using those same bytes. Preview, review-only and native request
emission never readmit. Missing Git objects require separate caller preparation;
the packet builder never fetches. Ready proves harness transport fit, not actual
provider consumption or permission for another supplier review round.

## Workflow

1. Resolve the train roadmap path (explicit arg or the user-supplied path).
2. Inspect admission state with `phase-loop train-status --train <file>`.
   The real draft-publication command below runs preflight before any PR opens.
3. Open draft PRs across all nodes in topo order:
   `phase-loop run-train --train <file>`
   The coordinator runs each repo's `run_loop` in series; a preflight failure
   stops before any PR is opened.
4. After all draft PRs are admitted, prepare the zero-model preview:
   `phase-loop run-train --train <file> --governed --review-only --review-material material.json --preview-review /absolute/empty/preview --json`.
   Inspect packet scope, evidence, certificates and `receipt.ready`. Ready means
   material preparation, not source approval. Review without merging using
   `phase-loop run-train --train <file> --governed --review-only --review-material material.json`.
5. On approval, re-run `phase-loop run-train --train <file> --governed`. The
   coordinator merges upstream nodes first, then re-verifies
   each downstream node against the upstream MERGED SHA before merging it.
   A re-verify failure halts the merge at that node; upstream merges are
   forward-only (never reverted).
6. Inspect the outcome: `phase-loop train-status --train <file>`.

## Failure Diagnostics

- `preflight_failed`: one or more nodes failed preflight checks; zero PRs were
  opened. Fix the reported issues and re-run.
- `drafts_open`: draft PRs opened; merge phase not yet run. Pass `--governed`
  to continue to review and merge.
- `review_approved`: train-level review approved under `--review-only`; ZERO merges.
  Re-run with `--governed`; unchanged bound packets may reuse approval.
- `review_only_requires_admitted_prs`: `--review-only` refused before any publication
  (a node lacks an admitted open PR, or a prebuilt workspace HEAD is not its admitted head).
  Bounded-mode note: for a prebuilt node with upstream edges this is the terminal
  status under the coordinator today.
- `review_halted`: the train-level panel did not approve; `terminal_blocker`
  carries `human_required=False` (the block is a non-human review terminal).
  No nodes were merged. Re-run after addressing review findings.
- `merge_halted`: upstream node(s) merged but a downstream re-verify failed;
  the failed node and all its dependents are blocked. The forward-only guard
  means already-merged nodes stay merged. Fix the integration issue and resume.
- `merge_failed`: a merge call returned an error (e.g. conflict, branch
  protection). The ledger records the failed node as `blocked`. Fix and resume.

## Resume

The coordinator is crash-resumable. If a run is interrupted, re-invoke the
same command with `--governed`; the ledger state drives which nodes are skipped
(already merged), re-verified (upstream merged but downstream not yet merged),
or retried (blocked).

Packet inputs are immutable Git-object snapshots of full admitted PR scope, not
node-label-filtered diffs. Local command results and generated-subtree disposal
claims are operator attestations. Certificates prove deletion mechanics, not
generatedness; their full inventories remain operator-only. Changed base/head,
criteria, context or evidence invalidate cached approval. Missing historical
packets on partial resume hold; do not reconstruct them from current main.
The complete rendered prompt must fit 512 KiB; do not truncate or spend extra
rounds to work around the bound. See `docs/phase-loop/cross-repo-train-authoring.md`
for the manifest and attestation schemas.
