# phase-loop-runtime

The harness-neutral **phase-loop** orchestration runtime and CLI. It drives the
roadmap → plan → execute workflow by dispatching each phase to whatever harness you
choose (Claude / Codex / Gemini / OpenCode); the runtime itself makes no model calls.
Part of the public [`agent-harness`](https://github.com/Consiliency/agent-harness)
monorepo (Apache-2.0).

## Install

Most users should use the repo's installer (it also installs the workflow skills):

```sh
git clone https://github.com/Consiliency/agent-harness
agent-harness/install-agent-harness.sh --harness claude
```

To install just this runtime package directly (e.g. as a pinned dependency):

```sh
# isolated tool install:
uv tool install "git+https://github.com/Consiliency/agent-harness@v0.1.5#subdirectory=phase-loop-runtime"
# …or into the current environment:
pip install "git+https://github.com/Consiliency/agent-harness@v0.1.5#subdirectory=phase-loop-runtime"
```

This exposes two console scripts — `phase-loop` and `codex-phase-loop` — both calling
`phase_loop_runtime.cli:main`. The canonical protocol document ships in the wheel as
package data and is also installed to `share/phase-loop-runtime/protocol/protocol.md`.

## Roadmap validation

