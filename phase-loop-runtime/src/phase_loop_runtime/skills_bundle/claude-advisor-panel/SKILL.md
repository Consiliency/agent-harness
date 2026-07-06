---
name: claude-advisor-panel
description: Run a customizable cross-vendor advisor board (formerly advisor-panel; that name remains a working alias) through the agent-harness runtime primitive when a high-stakes change needs independent review evidence.
---

# Advisor Board

Use this skill when a plan, implementation diff, release closeout, or other high-stakes artifact needs an independent cross-vendor review board. This skill was formerly named `advisor-panel`; that name still resolves as an alias, so existing instructions that say "advisor-panel" keep working.

## Source Of Truth

The advisor-board (formerly advisor-panel) implementation is owned by `agent-harness`:

- Runtime primitive: `phase_loop_runtime.panel_invoker`
- Board model: `phase_loop_runtime.advisor_board` (seats, boards, resolver, validation)
- Entry points: `available_panel_legs`, `invoke_panel`, and `invoke_panel_request` (from a `PanelRequest`)
- Governed workflow integration: phase-loop governed review/pre-merge paths

Do not call dotfiles advisor-panel scripts, copy provider-specific shell scripts, or introduce a separate implementation in the skill body. The skill is a thin operator guide over the runtime primitive.

## Reference, Don't Inline

**Point at artifact files by path (`artifact_ref`); do not paste content into the call.** The runtime reads and stages them for you, so your own context stays lean even for a 20k+ token bundle.

- `artifact_ref="path/to/bundle.md"` (or a list of paths) — the runtime reads the file(s) off disk and stages `review-bundle.md`. A single path is used verbatim; multiple paths are concatenated deterministically under per-file headers.
- `brief_ref="path/to/brief.md"` — compose any large review brief in a file; the runtime stages it as `review-instructions.md`. Omit it to use the built-in review/advisory brief.
- Pass paths, not content: a missing ref path fails closed with a clear error (never a silent empty review), and a large INLINE artifact logs a steering warning pointing you back to `artifact_ref`.
- `artifact: str` still works unchanged for small inline material; `artifact_ref` wins if both are given.

## Use

1. Prefer the repo's governed phase-loop path when reviewing phase execution or pre-merge work.
2. For a standalone smoke or diagnostic, stage the review material in a file and pass its path via `artifact_ref` to `phase_loop_runtime.panel_invoker.invoke_panel`.
3. Require every leg to end with `AGREE`, `PARTIALLY AGREE`, or `DISAGREE`.
4. Treat `EMPTY`, `TIMEOUT`, `ERROR`, `DEGRADED`, and `UNAVAILABLE` as structured evidence, not successful reviews.
5. Keep provider API keys out of the environment; the runtime strips known API-key variables and uses local subscription CLIs.

## Standalone Smoke Shape

```python
from phase_loop_runtime.panel_invoker import available_panel_legs, invoke_panel

panel = invoke_panel("", available_panel_legs(), artifact_ref="path/to/bundle.md")
for leg in panel.legs:
    print(leg.leg, leg.status)
```
