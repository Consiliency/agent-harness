# SCHED Worktree Recovery Ratification

## Decision

SCHED adopts a leased, generation-addressed lifecycle for phase worktrees. This
is the maintainer-approved third framing recorded by the accepted SCHED planning
package (Consiliency/agent-harness#616); it is a decision record, not a runtime
implementation or a recovery claim.

The creator acquires a POSIX `flock` lease before exposing a worktree handle and
returns the handle's exact generation, path, temporary branch, target branch,
base SHA, and live lease authority to every consumer. A launcher-owned supervisor
inherits that authority through `pass_fds`, owns the executor session and complete
process-tree reaping, and retains the shared open-file description until the tree
is proved empty. An executor closing its inherited descriptor, or its parent
exiting while a descendant remains, is therefore not a release of lifecycle
authority.

Normal teardown retains the active lease through final authenticated inventory and
removal, then closes it. Crash-residual reclamation instead acquires only a
released lease, non-blockingly, on a proven same-kernel local filesystem; it holds
that acquired lease through removal. Both paths require stable inventories with no
tracked, untracked, ignored, committed, handoff, symlink, or special-file state.
Any uncertainty, live lease, scan drift, unsupported proof, or recoverable byte
preserves the generation and branch.

An occupied or preserved generation is never force-removed. Creation mints a
collision-resistant generation-specific path and temporary branch, and downstream
dispatch consumes the returned handle rather than reconstructing an active path
from phase or branch strings. Preserved bytes are recovery evidence only: neither
their presence nor a branch reference authorizes checkpoint/resume inference.

## Rejected Designs

The following complete design set is rejected for SCHED implementation:

- The current deterministic recreate path: it calls `git worktree remove --force`
  for an occupied path and deletes the deterministic temporary branch before a
  replacement is created. It cannot preserve recoverable state.
- Draft Consiliency/agent-harness#354's age/mtime and clean/merged heuristic. Age,
  directory status, and a branch ref are not liveness or byte-preservation
  authority; its ignored-content exception also makes an ignored handoff-only
  candidate appear empty.
- The superseded salvage/reuse proposals in Consiliency/agent-harness#625 and
  Consiliency/agent-harness#626. Canonical-path reuse conflicts with generation
  addressing, and their design does not establish the required active-owner lease
  exclusion or stable complete inventory.
- Resume-first behavior and treating `.dev-skills/handoffs/` as session
  checkpoints. A handoff is durable recoverable state, not proof that execution
  can be resumed; manual, failed, blocked, or ambiguous closeout preserves its
  exact generation and bytes.
- Deletion based on PID, process-parent exit, mtime, directory age, a detached
  branch, a `--force` invocation, or any one incomplete inventory. None proves
  both an inactive owner and an empty candidate.

## Reviewed Ancestry Receipt

On 2026-08-25, this lane fetched `origin/main` and recorded the pre-landing
canonical main tip as `bab3bbc7038ed5b01df8216051051f3796bfe3ba`. The selected
lane worktree began at `7a6f2e10d3acc29f11a458f81146307504cb41b9`, whose sole
parent is that fetched canonical tip. The lifecycle commit is therefore a
record-only descendant of the reviewed canonical base; this receipt does not
claim a runtime landing, a test landing, or a new canonical-main commit.

The direct lifecycle source at that base still demonstrates the rejected behavior:
`create_phase_worktree` deterministically computes its path and temporary branch,
force-removes an existing worktree, and deletes an existing temporary branch.
SL-0 changes none of those bytes. Those source changes are reserved for the
subsequent owned lanes after their immutable RED boundary.

## Historical Worktree-Loss Disposition

Fresh remote metadata on 2026-08-25 confirms these surviving committed tips:

| Ref | Tip |
| --- | --- |
| `refs/heads/feat/advisor-board-abdreg` | `4c603c3203dd926d010c9f80be572659ed1144c0` |
| `refs/heads/phase/abdresolve` | `582037e0f4985e1ed5b8d8405fb1126e771f4b06` |

The removed `phase/abdresolve` worktree's 25 uncommitted files remain unknown and
unrecovered. This is the accepted `EC-SCHED-7` residual disposition: preserve the
two surviving committed tips, record the loss without smoothing it into a
successful recovery claim, and never use the surviving refs as substitutes for
the missing bytes.

## Scope Boundary

This record provides `SCHED_RECOVERY_DECISION` for SL-1 and SL-4. It intentionally
does not change tests, runtime code, planning artifacts, manifests, or lifecycle
state; it produces no phase interface-freeze gate on its own.
