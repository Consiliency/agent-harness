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
paste raw logs, secrets, host paths, or protected evidence-source contents.

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

An early draft describes current scope and marks pending implementation and
verification. Before an agent-owned PR becomes ready, inspect its existing body
and refresh the title and agent-authored text using the final diff and evidence.
Repeat after material implementation, verification, or comparison-base changes
before merge. Reassessment does not automatically invoke advisors or authorize merge.

Preserve human additions, plan/review/dependency links, repository-qualified issue
and PR references, and machine-readable directives such as `Roadmap-Disposition:`
on their own lines. When ownership of existing text is unclear, preserve it and
append a clearly scoped update rather than replacing the whole body. Use an
explicit title and a body file for authorized interactive creation or editing.

For adapter/broker-owned publication, compose before transaction preparation,
persist the body, and reuse its exact bytes on retry. The adapter's commit subject
becomes the title. An admitted body is not reformatted, and interactive guidance
does not authorize edits to runner/broker-owned descriptions.

Concepts adapted from [Matt Pocock's PR skill](https://github.com/mattpocock/skills/blob/main/skills/engineering/pr/SKILL.md),
which credits Dex Horthy and Humanlayer's show-me skill.
