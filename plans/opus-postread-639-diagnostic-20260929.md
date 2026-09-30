# agent-harness#639: exact-session diagnostic closeout

## Observed facts

Owned branch: `codex/opus-postread-639-20260929`, fresh input main
`b6a482faf7177ce5082267d584a689b2b7c95607`. Talk-to-Tux source is frozen on its
separate owned migration worktree; no running application, KVM, audio, clipboard
or inference endpoint has been changed.

Claude Code 2.1.285 matches the current upstream release. First-party subscription
preflight passed. Both launches use the source self-PTY adapter, Opus 5.5/max,
Read-only tools, no API/print-mode/model/permission fallback, and a unique exact
session. Raw debug traces remain local, mode 0600 in mode 0700 directories,
excluded from Git by scoped private-prefix ignore files. They are never published.

The baseline completed six Reads and observed a native CLI stream-first-chunk
event 1.363 seconds after the final tool result. No subsequent assistant event
appeared before `claude_tui_stalled`: elapsed 198.7s, progress age 180.1s. This
rules out a never-submitted prompt or a wholly inaccessible Read tool for this
run, not provider/transport/CLI internal failure or slow hidden processing.

One controlled same-input run used a 600-second silence limit and 900-second
hard backstop and completed AGREE. It resumed after 410.114s; native usage
records 45,230 thinking tokens in that turn. The ordinary 180s cutoff can
prematurely reclaim productive hidden reasoning, not merely a wedged spinner.
That does not attribute the failed baseline to a provider outage or prove a
universal safe silence duration. Production timeout policy is unchanged.
Process presence and completed tools never count as a verdict.

The completed source-bound review has 34 successful Read steps across 32
unique paths, zero tool errors, pinned Opus 5.5/max and all current source and
sealed/native receipts read. Three outside-root paths are public CPython 3.12
library sources, not private/neighboring transcripts. Independent source hashes
match the Talk-to-Tux freeze and its existing sealed runner still validates
`ok`. Receipts are preserved under its `reviews/round6/opus-completed/`; the
previous missing verdict is not overwritten. No extra retry/nudge was needed.

The public Claude status page reports operational service at the diagnostic
time; the earlier September 29 incident ended hours before these runs. That is
not proof that this particular stream is healthy. Upstream reports show related
first-chunk-then-silence symptoms on different models/versions/platforms, so they
are investigative leads rather than attribution or grounds for a downgrade:

- [Claude status](https://status.claude.com/)
- [claude-code#72639](https://github.com/anthropics/claude-code/issues/72639)
- [claude-code#25979](https://github.com/anthropics/claude-code/issues/25979)
- [claude-code#66095](https://github.com/anthropics/claude-code/issues/66095)

## Narrow implemented repair

The existing stalled marker lacked exact-session tool progress diagnostics.
`panel_invoker._claude_exact_tool_diagnostic` now emits only matched-result and
pending-tool counts and whether a later assistant event exists. Missing exact
binding or unreadable transcript remains unknown. It does not search neighbors,
expose tool IDs/content, reset heartbeat, extend timeout, retry, or confer output
authority. The existing typed status remains `claude_tui_stalled`.

Five new focused test cases cover matched and pending tools, later-assistant
presence, malformed input, missing exact binding, and a real wedged PTY where
completed Reads cannot authorize a verdict or extend the clock. Focused run:
244 passed in 34.94s. Baseline before the patch: 239 passed in 35.04s.
Independent read-only Sol CLI review AGREE, with actual source/test/plan reads.
Its malformed-role/neighbor coverage and streaming-parser suggestions are
nonblocking. No tests or private traces were read/executed by that reviewer.

The initial full runtime run timed out at 1200s, at 72% with two failure markers;
its runner artifact remains `nonzero_exit`. Failure localization identified:

- The optional historical dotfiles snapshot selected a shared checkout whose
  editor-added config name is rejected by the strict authority guard. A clean,
  separate fixture clone passes the exact test (1 passed, 25.21s); neither the
  shared config nor the production guard changed.
- The CONFORM provenance test correctly rejects an uncommitted candidate
  (`candidate_clean=False`); all required historical objects are present. A
  local owned-path checkpoint supplies real clean identity, not a mocked result.

The clean candidate then exposed a historical archive-seal mismatch. A
controlled replay proves that process umask 002 changes the archive digests;
022 reproduces all four frozen documents byte-for-byte. Neither document seals
nor assertions are changed. The owned isolated-full run was interrupted after
that reproducer, retaining its `nonzero_exit` receipt and buffered result:
3 failed, 3944 passed, 84 skipped, 598 deselected. The three recorded failures
are two canonical `/usr/bin/true` assumptions on Display's now-symlinked tool
and a synthetic-helper startup deadline. No host tool or deadline is changed.

Full-suite acceptance now requires the same original inventory in a committed,
source-equivalent Ubuntu 24.04/Python 3.12 test clone with umask 022, locked
requirements and the read-only fixture. The isolated container has no host
credentials/config/raw traces or host network, is not privileged, and is capped
at four CPUs, 4GiB/no swap and 1024 PIDs. Its artifact is under the owned private
`container-checkout/phase-loop-runtime/.dev-skills/verification/opus-postread-639-20260929/container-full/verification.json`
prefix. No pass or installed-host route qualification is claimed before that
runner completes and validates. Two initial runner setup
failures are preserved, not relabeled: a Python pin was incorrectly authored
as a version string rather than an executable, then the monorepo root included
the unrelated Dagger Python 3.14 floor. Corrected verification targets the
runtime package and its explicit installed Python 3.12 interpreter. The declared
consiliency-contract floor remains unverified in source mode (test warning);
the locked environment installs consiliency-contract 0.6.5.

## Acceptance and preservation

The diagnostic patch is not a global liveness-policy cure. The controlled
caller allowance restored a substantive Opus verdict; all four manual lenses
now approve only the inactive worker scope, not a fabricated governed-board
receipt. Existing three reviewer verdicts and 3863 application passes are
retained alongside the actual Opus review, not substituted for it. Whole
Talk-to-Tux migration acceptance remains blocked on production symbol/operation
freeze, parity, port/cutover and packaging. Original in-process memory/parity
failures stay failed evidence. Source is unchanged after its accepted freeze.

No deployment, publication, merge, worktree prune, global CLI upgrade/downgrade
or source changes outside the declared owned paths have occurred. An owned-path
local verification checkpoint is not a published release. Only owned
private evidence and the runtime diagnostic/test/plan delta are new here.
Best-effort manifest update warned that no entry exists; it did not mutate an
unrelated manifest. `doc_delta_decision=no_doc_delta`: only internal private
diagnostic tail fields change, not public CLI/status/config contracts.
