# phase-loop-runtime

Vendored phase-loop runtime package for this dotfiles repository.

Install locally from the repository root:

```bash
python3 -m pip install -e file://$PWD/vendor/phase-loop-runtime
```

The editable install exposes two console scripts:

- `phase-loop`
- `codex-phase-loop`

Both commands call `phase_loop_runtime.cli:main` and keep the existing parser
and version behavior. The canonical protocol document is bundled at
`protocol/protocol.md`.

This package is vendored for v18 and is not published to PyPI in this phase.

## Skills Bundle

The vendored runtime also exposes the harness-neutral Skills Bundle installer.
Workflow skill sources live under `vendor/phase-loop-skills/` with unprefixed
base directories and optional `_overrides/<harness>/` overlay directories.

Use `phase-loop install` to install harness-prefixed workflow skills:

```bash
phase-loop install --harness codex --source vendor/phase-loop-skills --symlink --dry-run
phase-loop install --harness codex --source vendor/phase-loop-skills --symlink --apply
```

Path resolution is provided by `phase_loop_runtime.skill_paths`. The resolver
keeps handoffs repo-local, preserves harness-specific reflection roots, and
documents the default install roots for Claude, Codex, Gemini, and OpenCode.
