# PR writing

Explain the final change to a reviewer who has not read the conversation. Follow
the destination repository's PR template and vocabulary. Keep small and docs-only
PRs short; section names and diagrams are optional.

## Problem and resulting behavior

Lead with the problem and what changes for a user or consumer. A concrete
trigger and before/after behavior can help. Describe the final implementation;
rewrite stale scope or abandoned approaches out of the agent-authored narrative.

Ground the explanation in the actual PR comparison base and current implementation
diff, not the latest commit alone or the original plan. Use `git diff <base>...HEAD`
for committed work. Before an adapter commits, include the audited owned worktree
changes too. Reassess if the implementation or comparison base changes.

Give a few useful repository-relative paths and exact function/symbol names that
you inspected. Add line locations only when checked against the cited revision.
GitHub source links use an existing commit; deleted code points to its base
revision. Do not guess a future publication SHA. Distinguish authored sources
from regenerated outputs, and changed boundaries from inspected callers.

Use a small diff sketch, pseudocode, call tree, or diagram when it explains an
otherwise difficult change. Preserve existing screenshot requirements for UI work.
Do not invent parser-derived seams, requirement mappings, or a complete blast
radius from a file list.

## Evidence and limits

Summarize observed commands, exit status, and relevant results from the current
verification artifact. State whether verification was complete, targeted, partial,
skipped, or exempted, with the applicable reason. Keep evidence redacted and do not
paste raw logs, secrets, host paths, or protected evidence-source contents. For a
security fix, keep the weakness, its trigger, and any exploit path out of public PR
and commit text; describe the change neutrally and use the repository's private
disclosure channel for the details.

Claim failing-before/passing-after evidence only if both were observed. Tests
passing supports the tested behavior, not every inferred consequence. Existing
spec goal IDs are references, never rewritten definitions of completion.

## Consumers and rollback

Identify the affected interfaces, downstream consumers, and known compatibility
changes. Explain how to undo the change and any material limits: data migrations,
destructive effects, external state, or consumer coordination. Say when there are
no known special rollback constraints; do not manufacture an exercise for a
trivial reversible edit. Separate observed dependencies from possible impact.

## Ownership and refresh

An interactive agent-owned PR is the PR this session created and recorded by URL
in its repository-matching handoff. An existing PR found on a branch is not enough
to establish ownership. Keep the last agent-authored title and block in that handoff.
An early draft marks pending implementation and verification. Use one delimited
agent block:

```markdown
<!-- agent-harness:pr-description:start -->
<agent-authored implementation description>
<!-- agent-harness:pr-description:end -->
```

At closeout, and after material implementation, verification, or comparison-base
changes before merge, read `gh pr view <pr> --json title,body` before composing.
Replace only the single delimited block if it still equals this session's last
authored block; preserve all other text. If the block was human-edited, absent, or
ambiguous, preserve the body and append a clearly scoped implementation update.
Change the title only if it still equals the last agent-authored title; otherwise
omit `--title` and retain the human title.

Immediately before the edit, re-read the title/body. If either changed while
composing, append the update to that latest body and omit `--title`; do not submit
the stale full-body replacement. Re-fetching reduces lost updates but is not an
atomic compare-and-swap with GitHub. Use the actual merged body file for the edit,
and save the successful authored title/block and PR URL in the handoff.

Refresh before initial readiness. A failed update leaves an initial draft in draft.
For an already-ready PR, report `description refresh failed`, identify the PR, and
do not report its description as current or proceed to merge. Do not imply a failed
edit changed its draft status. Reassessment does not automatically invoke advisors
or authorize merge.

Preserve human additions, plan/review/dependency links, repository-qualified issue
and PR references, and machine-readable directives such as `Roadmap-Disposition:`
on their own lines. When ownership of existing text is unclear, preserve it and
report that refresh belongs to its publication owner. Use an
explicit title and a body file for authorized interactive creation or editing.

For adapter/broker-owned publication, compose before transaction preparation,
persist the body in private Git state, and reuse its exact bytes on retry.
Resolve the Git common directory with `git rev-parse --path-format=absolute --git-common-dir`.
Use `<git-common-dir>/phase-loop-pr-text/<run-id>/body.md`, outside checked-out
source (and outside a linked worktree), with directory mode 0700 and file mode 0600.
Record its path and SHA-256 in the local handoff; do not stage it. The adapter's commit subject
becomes the title. An admitted body is not reformatted, and interactive guidance
does not authorize edits to runner/broker-owned descriptions.

Concepts adapted from [Matt Pocock's PR skill](https://github.com/mattpocock/skills/blob/main/skills/engineering/pr/SKILL.md),
which credits Dex Horthy and Humanlayer's show-me skill.
