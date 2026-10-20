# Codex execute-phase worker briefs

Use only after explicit user authorization and verification that the DAG-ready lanes are disjoint and have scheduler-owned worktree assignments. This procedure does not authorize peer harness launches; retain the entrypoint's typed `DelegationRequest` boundary.

For every worker brief:

- State that they are not alone in the codebase.
- Assign exact owned files or globs.
- List files they may read but not edit.
- Tell them not to revert unrelated changes.
- Require a final response with changed paths, tests run, failures, and blockers.
- Do not give two workers overlapping write ownership.

The main thread remains responsible for integrating results, reviewing diffs, running final verification, and resolving conflicts.
