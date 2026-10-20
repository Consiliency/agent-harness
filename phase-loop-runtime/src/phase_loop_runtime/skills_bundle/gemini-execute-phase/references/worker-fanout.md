# Worker fanout (gemini-execute-phase)

Use worker subagents only when the user explicitly authorizes parallel agent work and the DAG-ready lanes are disjoint.

For every worker brief:

- State that they are not alone in the codebase.
- Assign exact owned files or globs.
- List files they may read but not edit.
- Tell them not to revert unrelated changes.
- Require a final response with changed paths, tests run, failures, and blockers.
- Do not give two workers overlapping write ownership.

The main thread remains responsible for integrating results, reviewing diffs, running final verification, and resolving conflicts.
